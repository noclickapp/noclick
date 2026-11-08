"""SendFox API 1.6.0. Personal tokens; one request per operation, no automatic write retries.
Contract: https://sendfox.com/openapi.yaml. Some operations require a paid plan.
"""
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class SendfoxTokenCredential(BaseModel):
    model_config = ConfigDict(title="SendFox Personal Access Token", json_schema_extra={
        "x-credential-url": "https://sendfox.com/account/oauth",
        "x-credential-instructions": "Create a personal access token in SendFox Account → OAuth and paste it here. Your plan controls API access; some operations require Lifetime or Pro."})
    credential_type: Literal["sendfox_token"] = Field("sendfox_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Personal access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def validate_token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the personal access token, without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ListContactsConfig(_Input):
    """List contacts."""
    operation: Literal["list_contacts"] = "list_contacts"
    query: str | None = Field(None)
    unsubscribed: bool | None = Field(None)
    email: str | None = Field(None)
    per_page: int | None = Field(100, ge=1, le=1000)
    count_only: bool | None = Field(None)

class CreateContactConfig(_Input):
    """Create a new contact."""
    operation: Literal["create_contact"] = "create_contact"
    email: EmailStr = Field(..., min_length=1)
    first_name: str | None = Field(None)
    last_name: str | None = Field(None)
    lists: list[int] | None = Field(None, description='Array of list IDs to add the contact to')
    contact_tags: list[int] | None = Field(None, max_length=100, description="IDs of contact tags (see `/contact-tags`) to add, up to 100. Applies to existing and\nunsubscribed contacts too; a tag the contact already has is left alone. An ID the account\ndoesn't own returns 400 and nothing is written.\n")

class GetContactConfig(_Input):
    """Get a specific contact."""
    operation: Literal["get_contact"] = "get_contact"
    id: int = Field(..., ge=1)

class UpdateContactConfig(_Input):
    """Update a contact."""
    operation: Literal["update_contact"] = "update_contact"
    id: int = Field(..., ge=1)
    first_name: str | None = Field(None)
    last_name: str | None = Field(None)
    lists: list[int] | None = Field(None, description='Array of list IDs (replaces all current list memberships)')

class DeleteContactConfig(_Input):
    """Delete a contact."""
    operation: Literal["delete_contact"] = "delete_contact"
    id: int = Field(..., ge=1)

class UnsubscribeContactConfig(_Input):
    """Unsubscribe a contact by email."""
    operation: Literal["unsubscribe_contact"] = "unsubscribe_contact"
    email: EmailStr = Field(..., min_length=1)

class ListContactTagsConfig(_Input):
    """List contact tags."""
    operation: Literal["list_contact_tags"] = "list_contact_tags"

class CreateContactTagConfig(_Input):
    """Create a contact tag."""
    operation: Literal["create_contact_tag"] = "create_contact_tag"
    name: str = Field(..., min_length=1, max_length=191)
    color: str | None = Field(None, description='Optional brand palette hex color; auto-assigned when omitted.')

class GetContactTagConfig(_Input):
    """Get a contact tag."""
    operation: Literal["get_contact_tag"] = "get_contact_tag"
    id: int = Field(..., ge=1)

class UpdateContactTagConfig(_Input):
    """Update a contact tag."""
    operation: Literal["update_contact_tag"] = "update_contact_tag"
    id: int = Field(..., ge=1)
    name: str | None = Field(None, max_length=191)
    color: str | None = Field(None)

class DeleteContactTagConfig(_Input):
    """Delete a contact tag."""
    operation: Literal["delete_contact_tag"] = "delete_contact_tag"
    id: int = Field(..., ge=1)

class AttachContactTagConfig(_Input):
    """Attach a tag to a contact."""
    operation: Literal["attach_contact_tag"] = "attach_contact_tag"
    contact_id: int = Field(..., ge=1)
    tag_id: int = Field(..., ge=1)

class DetachContactTagConfig(_Input):
    """Remove a tag from a contact."""
    operation: Literal["detach_contact_tag"] = "detach_contact_tag"
    contact_id: int = Field(..., ge=1)
    tag_id: int = Field(..., ge=1)

class ListCampaignsConfig(_Input):
    """List campaigns."""
    operation: Literal["list_campaigns"] = "list_campaigns"
    list_id: int | None = Field(None, ge=1)

class GetCampaignConfig(_Input):
    """Get a specific campaign."""
    operation: Literal["get_campaign"] = "get_campaign"
    id: int = Field(..., ge=1)

class GetCampaignStatsConfig(_Input):
    """Get campaign performance statistics."""
    operation: Literal["get_campaign_stats"] = "get_campaign_stats"
    id: int = Field(..., ge=1)
    include_link_stats: bool | None = Field(False)
    link_limit: int | None = Field(50, ge=1, le=100)

class GetCurrentUserConfig(_Input):
    """Get current user information."""
    operation: Literal["get_current_user"] = "get_current_user"

class ListContactListsConfig(_Input):
    """List contact lists."""
    operation: Literal["list_contact_lists"] = "list_contact_lists"
    query: str | None = Field(None)

class CreateContactListConfig(_Input):
    """Create a new contact list."""
    operation: Literal["create_contact_list"] = "create_contact_list"
    name: str = Field(..., min_length=1)

class GetContactListConfig(_Input):
    """Get a specific contact list."""
    operation: Literal["get_contact_list"] = "get_contact_list"
    id: int = Field(..., ge=1)

class UpdateContactListConfig(_Input):
    """Update a contact list."""
    operation: Literal["update_contact_list"] = "update_contact_list"
    id: int = Field(..., ge=1)
    name: str | None = Field(None, max_length=191)
    public_description: str | None = Field(None, max_length=80, description="The name subscribers see on the unsubscribe and preference pages. Blank uses the list's own name.")
    subscriber_description: str | None = Field(None, max_length=500, description='What subscribers can expect from this list, shown below its name on those pages. Blank clears it.')

class DeleteContactListConfig(_Input):
    """Delete a contact list."""
    operation: Literal["delete_contact_list"] = "delete_contact_list"
    id: int = Field(..., ge=1)

class ListContactsInListConfig(_Input):
    """Get contacts in a list."""
    operation: Literal["list_contacts_in_list"] = "list_contacts_in_list"
    list_id: int = Field(..., ge=1)
    query: str | None = Field(None)
    status: Literal['subscribed', 'unsubscribed'] | None = Field(None)

class AddContactToListConfig(_Input):
    """Add a contact to a list."""
    operation: Literal["add_contact_to_list"] = "add_contact_to_list"
    list_id: int = Field(..., ge=1)
    contact_id: int = Field(..., description='ID of the contact to add')

class RemoveContactFromListConfig(_Input):
    """Remove a contact from a list."""
    operation: Literal["remove_contact_from_list"] = "remove_contact_from_list"
    list_id: int = Field(..., ge=1)
    contact_id: int = Field(..., ge=1)

SendfoxOperation = Annotated[Union[ListContactsConfig, CreateContactConfig, GetContactConfig, UpdateContactConfig, DeleteContactConfig, UnsubscribeContactConfig, ListContactTagsConfig, CreateContactTagConfig, GetContactTagConfig, UpdateContactTagConfig, DeleteContactTagConfig, AttachContactTagConfig, DetachContactTagConfig, ListCampaignsConfig, GetCampaignConfig, GetCampaignStatsConfig, GetCurrentUserConfig, ListContactListsConfig, CreateContactListConfig, GetContactListConfig, UpdateContactListConfig, DeleteContactListConfig, ListContactsInListConfig, AddContactToListConfig, RemoveContactFromListConfig], Field(discriminator="operation")]

class SendfoxFullConfig(NodeConfig[SendfoxOperation, SendfoxTokenCredential]):
    pass

OPERATIONS = {'list_contacts': {'method': 'GET', 'path': '/contacts', 'paths': [], 'query': ['query', 'unsubscribed', 'email', 'per_page', 'count_only'], 'body': []}, 'create_contact': {'method': 'POST', 'path': '/contacts', 'paths': [], 'query': [], 'body': ['email', 'first_name', 'last_name', 'lists', 'contact_tags']}, 'get_contact': {'method': 'GET', 'path': '/contacts/{id}', 'paths': ['id'], 'query': [], 'body': []}, 'update_contact': {'method': 'PATCH', 'path': '/contacts/{id}', 'paths': ['id'], 'query': [], 'body': ['first_name', 'last_name', 'lists']}, 'delete_contact': {'method': 'DELETE', 'path': '/contacts/{id}', 'paths': ['id'], 'query': [], 'body': []}, 'unsubscribe_contact': {'method': 'PATCH', 'path': '/unsubscribe', 'paths': [], 'query': [], 'body': ['email']}, 'list_contact_tags': {'method': 'GET', 'path': '/contact-tags', 'paths': [], 'query': [], 'body': []}, 'create_contact_tag': {'method': 'POST', 'path': '/contact-tags', 'paths': [], 'query': [], 'body': ['name', 'color']}, 'get_contact_tag': {'method': 'GET', 'path': '/contact-tags/{id}', 'paths': ['id'], 'query': [], 'body': []}, 'update_contact_tag': {'method': 'PATCH', 'path': '/contact-tags/{id}', 'paths': ['id'], 'query': [], 'body': ['name', 'color']}, 'delete_contact_tag': {'method': 'DELETE', 'path': '/contact-tags/{id}', 'paths': ['id'], 'query': [], 'body': []}, 'attach_contact_tag': {'method': 'POST', 'path': '/contacts/{contact_id}/tags/{tag_id}', 'paths': ['contact_id', 'tag_id'], 'query': [], 'body': []}, 'detach_contact_tag': {'method': 'DELETE', 'path': '/contacts/{contact_id}/tags/{tag_id}', 'paths': ['contact_id', 'tag_id'], 'query': [], 'body': []}, 'list_campaigns': {'method': 'GET', 'path': '/campaigns', 'paths': [], 'query': ['list_id'], 'body': []}, 'get_campaign': {'method': 'GET', 'path': '/campaigns/{id}', 'paths': ['id'], 'query': [], 'body': []}, 'get_campaign_stats': {'method': 'GET', 'path': '/campaigns/{id}/stats', 'paths': ['id'], 'query': ['include_link_stats', 'link_limit'], 'body': []}, 'get_current_user': {'method': 'GET', 'path': '/me', 'paths': [], 'query': [], 'body': []}, 'list_contact_lists': {'method': 'GET', 'path': '/lists', 'paths': [], 'query': ['query'], 'body': []}, 'create_contact_list': {'method': 'POST', 'path': '/lists', 'paths': [], 'query': [], 'body': ['name']}, 'get_contact_list': {'method': 'GET', 'path': '/lists/{id}', 'paths': ['id'], 'query': [], 'body': []}, 'update_contact_list': {'method': 'PATCH', 'path': '/lists/{id}', 'paths': ['id'], 'query': [], 'body': ['name', 'public_description', 'subscriber_description']}, 'delete_contact_list': {'method': 'DELETE', 'path': '/lists/{id}', 'paths': ['id'], 'query': [], 'body': []}, 'list_contacts_in_list': {'method': 'GET', 'path': '/lists/{list_id}/contacts', 'paths': ['list_id'], 'query': ['query', 'status'], 'body': []}, 'add_contact_to_list': {'method': 'POST', 'path': '/lists/{list_id}/contacts', 'paths': ['list_id'], 'query': [], 'body': ['contact_id']}, 'remove_contact_from_list': {'method': 'DELETE', 'path': '/lists/{list_id}/contacts/{contact_id}', 'paths': ['list_id', 'contact_id'], 'query': [], 'body': []}}

class SendfoxNode(WorkflowNode):
    integration_type = "automation-sendfox"
    connection_evidence = ConnectionEvidence(noun="SendFox account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return SendfoxFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a SendFox personal access token")
        config = self.config.config
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec["path"]
        for key in spec["paths"]:
            path = path.replace("{" + key + "}", str(values[key]))
        params = {key: (str(values[key]).lower() if isinstance(values[key], bool) else values[key]) for key in spec["query"] if key in values}
        body = {key: values[key] for key in spec["body"] if key in values}
        kwargs = {"params": params, "headers": {"Authorization": "Bearer " + self.config.credentials.access_token, "Accept": "application/json"}}
        if spec["body"]:
            if not body:
                raise ValueError("Provide at least one field to update")
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(spec["method"], "https://api.sendfox.com" + path, **kwargs)
        if response.is_error:
            # Preserve provider rejection text for credential verification.
            try:
                message = response.json().get("message", "SendFox request rejected")
            except (ValueError, AttributeError):
                message = "SendFox request rejected"
            message = str(message).replace(self.config.credentials.access_token, "[redacted]")
            return {"status": "error", "error": message, "http_status": response.status_code}
        response.raise_for_status()
        if response.status_code == 204:
            return {"status": "success", "http_status": 204}
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Expected a SendFox JSON object or array")
        return {"status": "success", "data": data, "http_status": response.status_code}
