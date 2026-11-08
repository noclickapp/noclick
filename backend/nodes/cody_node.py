"""Cody AI v1 operations, pinned to the provider's published OpenAPI 1.0 contract.

Each operation makes one authenticated request. Lists return one provider page,
including its pagination metadata. Upload URLs and stream URLs are returned for
subsequent use; this node does not follow them or upload files automatically.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://getcody.ai/api/v1"



class CodyApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cody API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://getcody.ai/settings/api",
            "x-credential-instructions": "Open Cody Settings → API Keys and copy an API key. Paste only the key, without the Bearer prefix. NoClick checks it by reading your bots.",
        })
    credential_type: Literal["cody_api_key"] = Field("cody_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the Cody API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)



class CodyListBotsConfig(_Input):
    """List Bots. Returns one provider page with pagination metadata."""
    operation: Literal["list_bots"] = Field("list_bots", json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, min_length=1, max_length=1000)


class CodyListConversationsConfig(_Input):
    """List Conversations. Returns one provider page with pagination metadata."""
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})
    bot_id: str | None = Field(None, min_length=1, max_length=1000)
    keyword: str | None = Field(None, min_length=1, max_length=1000)
    includes: Literal['document_ids'] | None = Field(None, min_length=1, max_length=1000)


class CodyCreateConversationConfig(_Input):
    """Create Conversation. Uses one Cody API request."""
    operation: Literal["create_conversation"] = Field("create_conversation", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    bot_id: str = Field(..., min_length=1, max_length=1000)
    document_ids: list[str] | None = Field(None, max_length=1000, description='Only documents that exist in the folders the bot has access to are allowed. You can give bot access to all folders if you wish to limit documents from your whole knowledge base.')


class CodyGetConversationConfig(_Input):
    """Get Conversation. Uses one Cody API request."""
    operation: Literal["get_conversation"] = Field("get_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9_-]+$")
    includes: Literal['document_ids'] | None = Field(None, min_length=1, max_length=1000)


class CodyUpdateConversationConfig(_Input):
    """Update Conversation. Uses one Cody API request."""
    operation: Literal["update_conversation"] = Field("update_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=1000)
    bot_id: str = Field(..., min_length=1, max_length=1000)
    document_ids: list[str] | None = Field(None, max_length=1000, description='Only documents that exist in the folders the bot has access to are allowed. You can give bot access to all folders if you wish to limit documents from your whole knowledge base.')


class CodyDeleteConversationConfig(_Input):
    """Delete Conversation. Uses one Cody API request."""
    operation: Literal["delete_conversation"] = Field("delete_conversation", json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9_-]+$")


class CodyListDocumentsConfig(_Input):
    """List Documents. Returns one provider page with pagination metadata."""
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})
    folder_id: str | None = Field(None, min_length=1, max_length=1000)
    conversation_id: str | None = Field(None, min_length=1, max_length=1000)
    keyword: str | None = Field(None, min_length=1, max_length=1000)


class CodyCreateDocumentConfig(_Input):
    """Create Document. Uses one Cody API request."""
    operation: Literal["create_document"] = Field("create_document", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    folder_id: str = Field(..., min_length=1, max_length=1000)
    content: str = Field(..., min_length=1, max_length=786432, description='Up to 768 KB of text or html only.')


class CodyCreateDocumentFromFileConfig(_Input):
    """Create Document from File. Uses one Cody API request."""
    operation: Literal["create_document_from_file"] = Field("create_document_from_file", json_schema_extra={"ui:hidden": True})
    folder_id: str = Field(..., min_length=1, max_length=1000)
    key: str = Field(..., min_length=1, max_length=1000, description='The key you receive after uploading a file. See [/uploads/signed-url](/operation/operation-get-uploads-signed-url)')


class CodyCreateDocumentFromWebpageConfig(_Input):
    """Create Document from Webpage. Uses one Cody API request."""
    operation: Literal["create_document_from_webpage"] = Field("create_document_from_webpage", json_schema_extra={"ui:hidden": True})
    folder_id: str = Field(..., min_length=1, max_length=1000)
    url: str = Field(..., min_length=1, max_length=8192, description='Valid and publicly accessible webpage URL.')


class CodyGetDocumentConfig(_Input):
    """Get Document. Uses one Cody API request."""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9_-]+$")


class CodyDeleteDocumentConfig(_Input):
    """Delete Document. Uses one Cody API request."""
    operation: Literal["delete_document"] = Field("delete_document", json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9_-]+$")


class CodyListFoldersConfig(_Input):
    """List Folders. Returns one provider page with pagination metadata."""
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, min_length=1, max_length=1000)


class CodyCreateFolderConfig(_Input):
    """Create Folder. Uses one Cody API request."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)


class CodyGetFolderConfig(_Input):
    """Get Folder. Uses one Cody API request."""
    operation: Literal["get_folder"] = Field("get_folder", json_schema_extra={"ui:hidden": True})
    folder_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9_-]+$")


class CodyUpdateFolderConfig(_Input):
    """Update Folder. Uses one Cody API request."""
    operation: Literal["update_folder"] = Field("update_folder", json_schema_extra={"ui:hidden": True})
    folder_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=1000)


class CodyListMessagesConfig(_Input):
    """List Messages. Returns one provider page with pagination metadata."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    conversation_id: str | None = Field(None, min_length=1, max_length=1000)
    includes: Literal['sources', 'usage'] | None = Field(None, min_length=1, max_length=1000)


class CodySendMessageConfig(_Input):
    """Send Message. Uses one Cody API request."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str = Field(..., min_length=1, max_length=1000)


class CodyGetMessageConfig(_Input):
    """Get Message. Uses one Cody API request."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})
    message_id: str = Field(..., min_length=1, max_length=1000, pattern=r"^[A-Za-z0-9_-]+$")
    includes: Literal['sources', 'usage'] | None = Field(None, min_length=1, max_length=1000)


class CodySendMessageForStreamConfig(_Input):
    """Send Message for Stream. Uses one Cody API request."""
    operation: Literal["send_message_for_stream"] = Field("send_message_for_stream", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., min_length=1, max_length=2000, description='Content can be upto 2000 characters.')
    conversation_id: str = Field(..., min_length=1, max_length=1000)
    redirect: Literal[False] = Field(False, description="Return a stream URL as JSON; no redirect or stream is followed.")


class CodyGetUploadsSignedUrlConfig(_Input):
    """Get Upload URL. Uses one Cody API request."""
    operation: Literal["get_uploads_signed_url"] = Field("get_uploads_signed_url", json_schema_extra={"ui:hidden": True})
    file_name: str = Field(..., min_length=1, max_length=1000, description='Original file name you want to upload, must contain the file extension.')
    content_type: str = Field(..., min_length=1, max_length=1000, description='MIME content type of the file.')


CodyConfig = Annotated[Union[
    CodyListBotsConfig,
    CodyListConversationsConfig,
    CodyCreateConversationConfig,
    CodyGetConversationConfig,
    CodyUpdateConversationConfig,
    CodyDeleteConversationConfig,
    CodyListDocumentsConfig,
    CodyCreateDocumentConfig,
    CodyCreateDocumentFromFileConfig,
    CodyCreateDocumentFromWebpageConfig,
    CodyGetDocumentConfig,
    CodyDeleteDocumentConfig,
    CodyListFoldersConfig,
    CodyCreateFolderConfig,
    CodyGetFolderConfig,
    CodyUpdateFolderConfig,
    CodyListMessagesConfig,
    CodySendMessageConfig,
    CodyGetMessageConfig,
    CodySendMessageForStreamConfig,
    CodyGetUploadsSignedUrlConfig
], Field(discriminator="operation")]



class CodyFullConfig(NodeConfig[CodyConfig, CodyApiKeyCredential]):
    pass


ROUTES = {'list_bots': ('GET', '/bots', None, ['keyword'], []),
 'list_conversations': ('GET', '/conversations', None, ['bot_id', 'keyword', 'includes'], []),
 'create_conversation': ('POST', '/conversations', None, [], ['name', 'bot_id', 'document_ids']),
 'get_conversation': ('GET', '/conversations/{id}', 'conversation_id', ['includes'], []),
 'update_conversation': ('POST',
                         '/conversations/{id}',
                         'conversation_id',
                         [],
                         ['name', 'bot_id', 'document_ids']),
 'delete_conversation': ('DELETE', '/conversations/{id}', 'conversation_id', [], []),
 'list_documents': ('GET', '/documents', None, ['folder_id', 'conversation_id', 'keyword'], []),
 'create_document': ('POST', '/documents', None, [], ['name', 'folder_id', 'content']),
 'create_document_from_file': ('POST', '/documents/file', None, [], ['folder_id', 'key']),
 'create_document_from_webpage': ('POST', '/documents/webpage', None, [], ['folder_id', 'url']),
 'get_document': ('GET', '/documents/{id}', 'document_id', [], []),
 'delete_document': ('DELETE', '/documents/{id}', 'document_id', [], []),
 'list_folders': ('GET', '/folders', None, ['keyword'], []),
 'create_folder': ('POST', '/folders', None, [], ['name']),
 'get_folder': ('GET', '/folders/{id}', 'folder_id', [], []),
 'update_folder': ('POST', '/folders/{id}', 'folder_id', [], ['name']),
 'list_messages': ('GET', '/messages', None, ['conversation_id', 'includes'], []),
 'send_message': ('POST', '/messages', None, [], ['content', 'conversation_id']),
 'get_message': ('GET', '/messages/{id}', 'message_id', ['includes'], []),
 'send_message_for_stream': ('POST',
                             '/messages/stream',
                             None,
                             [],
                             ['content', 'conversation_id', 'redirect']),
 'get_uploads_signed_url': ('POST', '/uploads/signed-url', None, [], ['file_name', 'content_type'])}



class CodyNode(WorkflowNode):
    integration_type = "automation-cody"
    connection_evidence = ConnectionEvidence(operation="list_bots", noun="bots", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return CodyFullConfig

    @staticmethod
    def _check_credential(data):
        credential = data.get("credentials")
        if credential is not None:
            if not isinstance(credential, dict) or credential.get("credential_type", "cody_api_key") != "cody_api_key":
                raise ValueError("Connect a Cody API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not isinstance(self.config, CodyFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Cody API key")
        config = self.config.config
        credential = self.config.credentials
        method, path, id_field, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        if id_field:
            path = path.replace("{id}", quote(values[id_field], safe=""))
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        if config.operation == "create_document" and len(config.content.encode("utf-8")) > 768 * 1024:
            raise ValueError("Document content must be at most 768 KB; use a file import for larger content")
        kwargs = {"params": params}
        if body_fields:
            kwargs["json"] = body
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}, **kwargs)
        if response.status_code < 200 or response.status_code >= 300:
            # Preserve the provider's refusal, including its HTTP status, for connection evidence.
            message = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"Cody API HTTP {response.status_code}: {message}")
        if not response.content:
            if config.operation not in {"delete_document", "delete_conversation", "create_document_from_file"}:
                raise ValueError("Cody returned an empty API response")
            return {"success": True, "operation": config.operation, "http_status": response.status_code}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Cody returned a non-JSON API response") from None
        if not isinstance(payload, dict):
            raise ValueError("Cody returned an unexpected API envelope")
        if config.operation.startswith("list_") and not isinstance(payload.get("data"), list):
            raise ValueError("Cody returned an unexpected list envelope")
        # Keep the native envelope: data, meta.pagination, sources, and usage remain available.
        return payload
