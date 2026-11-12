"""Mixmax API v1: sequences, templates, messages and unsubscribe management.

Contract: https://dash.readme.com/api/v1/api-registry/fznbiac0mvtf6k4i (1.0).
"""
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MixmaxAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Mixmax API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.mixmax.com/dashboard/settings/integrations",
            "x-credential-instructions": "Create an API token in Mixmax Settings > Integrations and paste it here. NoClick sends it in X-API-Token to api.mixmax.com. Use a personal API token; managed keys cannot access some account endpoints.",
        })
    credential_type: Literal["mixmax_api_token"] = Field("mixmax_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def clean_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without whitespace")
        return value


class MixmaxInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class MixmaxAddress(MixmaxInput):
    email: str = Field(..., min_length=3)
    name: str | None = None


class MixmaxRecipient(MixmaxInput):
    email: str = Field(..., min_length=3)
    variables: dict[str, str] | None = None
    scheduledAt: int | Literal[False] | None = Field(None, description="Unix milliseconds, or false to keep this recipient in draft.")


class MixmaxGetCurrentUserConfig(MixmaxInput):
    """Get current user; performs one API request."""
    operation: Literal["get_current_user"] = "get_current_user"


class MixmaxListSequencesConfig(MixmaxInput):
    """List sequences; performs one API request."""
    operation: Literal["list_sequences"] = "list_sequences"
    name: str | None = Field(None)
    folder: str | None = Field(None)
    limit: int | None = Field(None, ge=1, le=100)
    next: str | None = Field(None)


class MixmaxListSequenceRecipientsConfig(MixmaxInput):
    """List sequence recipients; performs one API request."""
    operation: Literal["list_sequence_recipients"] = "list_sequence_recipients"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    limit: int | None = Field(None, ge=1, le=50)
    offset: int | None = Field(None, ge=0)
    query: str | None = Field(None)


class MixmaxAddSequenceRecipientsConfig(MixmaxInput):
    """Add sequence recipients; performs one API request."""
    operation: Literal["add_sequence_recipients"] = "add_sequence_recipients"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    recipients: list[MixmaxRecipient] = Field(..., min_length=1)
    scheduledAt: int | None = Field(None, ge=1000000000000, le=9999999999999)
    enrich: bool | None = Field(None)
    allowMissingVariables: bool | None = Field(None)


class MixmaxCancelSequenceRecipientsConfig(MixmaxInput):
    """Cancel sequence recipients; performs one API request."""
    operation: Literal["cancel_sequence_recipients"] = "cancel_sequence_recipients"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    emails: list[str] = Field(..., min_length=1)


class MixmaxListSequenceFoldersConfig(MixmaxInput):
    """List sequence folders; performs one API request."""
    operation: Literal["list_sequence_folders"] = "list_sequence_folders"


class MixmaxCreateSequenceFolderConfig(MixmaxInput):
    """Create sequence folder; performs one API request."""
    operation: Literal["create_sequence_folder"] = "create_sequence_folder"
    name: str | None = Field(None)


class MixmaxGetSequenceFolderConfig(MixmaxInput):
    """Get sequence folder; performs one API request."""
    operation: Literal["get_sequence_folder"] = "get_sequence_folder"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class MixmaxUpdateSequenceFolderConfig(MixmaxInput):
    """Update sequence folder; performs one API request."""
    operation: Literal["update_sequence_folder"] = "update_sequence_folder"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(...)


class MixmaxDeleteSequenceFolderConfig(MixmaxInput):
    """Delete sequence folder; performs one API request."""
    operation: Literal["delete_sequence_folder"] = "delete_sequence_folder"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class MixmaxListTemplatesConfig(MixmaxInput):
    """List templates; performs one API request."""
    operation: Literal["list_templates"] = "list_templates"
    search: str | None = Field(None)
    limit: int | None = Field(None, ge=1, le=300)
    next: str | None = Field(None)


class MixmaxGetTemplateConfig(MixmaxInput):
    """Get template; performs one API request."""
    operation: Literal["get_template"] = "get_template"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class MixmaxUpdateTemplateConfig(MixmaxInput):
    """Update template; performs one API request."""
    operation: Literal["update_template"] = "update_template"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(None)
    title: str | None = Field(None)
    source: str | None = Field(None)


class MixmaxListMessagesConfig(MixmaxInput):
    """List messages; performs one API request."""
    operation: Literal["list_messages"] = "list_messages"
    limit: int | None = Field(None, ge=1, le=300)
    next: str | None = Field(None)


class MixmaxGetMessageConfig(MixmaxInput):
    """Get message; performs one API request."""
    operation: Literal["get_message"] = "get_message"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class MixmaxCreateDraftConfig(MixmaxInput):
    """Create draft; performs one API request."""
    operation: Literal["create_draft"] = "create_draft"
    to: list[MixmaxAddress] | None = Field(None)
    cc: list[MixmaxAddress] | None = Field(None)
    bcc: list[MixmaxAddress] | None = Field(None)
    subject: str | None = Field(None)
    body: str | None = Field(None)
    trackingEnabled: bool | None = Field(None)


class MixmaxUpdateMessageConfig(MixmaxInput):
    """Update message; performs one API request."""
    operation: Literal["update_message"] = "update_message"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    to: list[MixmaxAddress] | None = Field(None)
    cc: list[MixmaxAddress] | None = Field(None)
    bcc: list[MixmaxAddress] | None = Field(None)
    subject: str | None = Field(None)
    body: str | None = Field(None)
    trackingEnabled: bool | None = Field(None)


class MixmaxSendDraftConfig(MixmaxInput):
    """Send draft; performs one API request."""
    operation: Literal["send_draft"] = "send_draft"
    id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class MixmaxListUnsubscribesConfig(MixmaxInput):
    """List unsubscribes; performs one API request."""
    operation: Literal["list_unsubscribes"] = "list_unsubscribes"
    email: str | None = Field(None)
    limit: int | None = Field(None, ge=1, le=300)
    next: str | None = Field(None)


class MixmaxAddUnsubscribeConfig(MixmaxInput):
    """Add unsubscribe; performs one API request."""
    operation: Literal["add_unsubscribe"] = "add_unsubscribe"
    email: str = Field(...)
    name: str | None = Field(None)


class MixmaxRemoveUnsubscribeConfig(MixmaxInput):
    """Remove unsubscribe; performs one API request."""
    operation: Literal["remove_unsubscribe"] = "remove_unsubscribe"
    email: str = Field(...)


class MixmaxListMeetingInvitesConfig(MixmaxInput):
    """List meeting invites; performs one API request."""
    operation: Literal["list_meeting_invites"] = "list_meeting_invites"
    limit: int | None = Field(None, ge=1, le=300)
    next: str | None = Field(None)


# Mixmax's own MCP server: agents get its tools through a person's Mixmax sign-in.
MixmaxMcpCredential = mcp_credential("mixmax", "https://mcp.mixmax.com/mcp", app="Mixmax")
MixmaxCredential = Union[MixmaxAPITokenCredential, MixmaxMcpCredential]


MixmaxConfig = Annotated[Union[
    MixmaxGetCurrentUserConfig,
    MixmaxListSequencesConfig,
    MixmaxListSequenceRecipientsConfig,
    MixmaxAddSequenceRecipientsConfig,
    MixmaxCancelSequenceRecipientsConfig,
    MixmaxListSequenceFoldersConfig,
    MixmaxCreateSequenceFolderConfig,
    MixmaxGetSequenceFolderConfig,
    MixmaxUpdateSequenceFolderConfig,
    MixmaxDeleteSequenceFolderConfig,
    MixmaxListTemplatesConfig,
    MixmaxGetTemplateConfig,
    MixmaxUpdateTemplateConfig,
    MixmaxListMessagesConfig,
    MixmaxGetMessageConfig,
    MixmaxCreateDraftConfig,
    MixmaxUpdateMessageConfig,
    MixmaxSendDraftConfig,
    MixmaxListUnsubscribesConfig,
    MixmaxAddUnsubscribeConfig,
    MixmaxRemoveUnsubscribeConfig,
    MixmaxListMeetingInvitesConfig
], Field(discriminator="operation")]


class MixmaxFullConfig(NodeConfig[MixmaxConfig, MixmaxCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/v1/users/me'), 'list_sequences': ('GET', '/v1/sequences'), 'list_sequence_recipients': ('GET', '/v1/sequences/{id}/recipients/'), 'add_sequence_recipients': ('POST', '/v1/sequences/{id}/recipients/'), 'cancel_sequence_recipients': ('POST', '/v1/sequences/{id}/cancel'), 'list_sequence_folders': ('GET', '/v1/sequencefolders'), 'create_sequence_folder': ('POST', '/v1/sequencefolders'), 'get_sequence_folder': ('GET', '/v1/sequencefolders/{id}'), 'update_sequence_folder': ('PATCH', '/v1/sequencefolders/{id}'), 'delete_sequence_folder': ('DELETE', '/v1/sequencefolders/{id}'), 'list_templates': ('GET', '/v1/snippets'), 'get_template': ('GET', '/v1/snippets/{id}'), 'update_template': ('PATCH', '/v1/snippets/{id}'), 'list_messages': ('GET', '/v1/messages'), 'get_message': ('GET', '/v1/messages/{id}'), 'create_draft': ('POST', '/v1/messages'), 'update_message': ('PATCH', '/v1/messages/{id}'), 'send_draft': ('POST', '/v1/messages/{id}/send'), 'list_unsubscribes': ('GET', '/v1/unsubscribes'), 'add_unsubscribe': ('POST', '/v1/unsubscribes'), 'remove_unsubscribe': ('DELETE', '/v1/unsubscribes'), 'list_meeting_invites': ('GET', '/v1/meetinginvites')}


class MixmaxNode(WorkflowNode):
    integration_type = "automation-mixmax"
    credential_provider_labels = {"mixmax": "Mixmax Account"}
    connection_evidence = ConnectionEvidence(noun="Mixmax account", identity_operation="get_current_user", identity_keys=("_id",))

    @classmethod
    def get_config_model(cls):
        return MixmaxFullConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Mixmax API token")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", quote(values.pop("id"), safe=""))
        kwargs: dict[str, Any] = {}
        if method == "GET":
            kwargs["params"] = values
        elif values:
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.mixmax.com" + path,
                headers={"X-API-Token": credential.api_token, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Do not expose echoed tokens, message bodies or recipient data in errors.
            raise ValueError(f"Mixmax API returned HTTP {response.status_code}")
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "acknowledged": True}
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("Mixmax returned an unexpected JSON response")
        if isinstance(body, dict) and (body.get("error") or body.get("errors")):
            raise ValueError("Mixmax returned an API error")
        if config.operation == "get_current_user" and (not isinstance(body, dict) or not isinstance(body.get("_id"), str) or not body["_id"]):
            raise ValueError("Mixmax did not return an authenticated user ID")
        return {"status": "success", "http_status": response.status_code, "data": body}
