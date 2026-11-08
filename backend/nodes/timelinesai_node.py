"""TimelinesAI Public API 1.3.0: single-request operations and native token auth.

Contract: https://timelinesai.mintlify.app/docs/openapi/public_api_spec.yaml
List operations return a single provider page, including its pagination metadata.
Message sends consume provider credits; the API acknowledgement is not delivery.
"""
from typing import Annotated, Literal, Union
from datetime import datetime
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.timelines.ai/integrations/api"

class TimelinesAIAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="TimelinesAI API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.timelines.ai/integrations/api/",
            "x-credential-instructions": "Copy your API token from the Public API page in TimelinesAI. Paste the token here. Message sends consume your workspace sending quota."})
    credential_type: Literal["timelinesai_api_token"] = "timelinesai_api_token"
    api_token: str = Field(..., min_length=1, max_length=4096, title="API Token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def no_nul(cls, value):
        def check(v):
            if isinstance(v, str) and "\0" in v: raise ValueError("TimelinesAI strings cannot contain NUL")
            if isinstance(v, dict):
                for item in v.values(): check(item)
            if isinstance(v, list):
                for item in v: check(item)
        check(value)
        return value

class ListChats(Input):
    """Get full or filtered list of all chats in the Workspace."""
    operation: Literal["list_chats"] = "list_chats"
    label: str | None = Field(None , description='filters chats having at least one of specified labels (comma-separated)')
    whatsapp_account_id: str | None = Field(None , description='filters chats belonging to one of the specified WhatsApp accounts (in wid format, comma-separated)')
    group: bool | None = Field(None , description='filters chats that are either group chats (true) or direct chats (false)')
    responsible: str | None = Field(None , description='filters chats assigned to specific users (denoted by email address, comma-separated)')
    name: str | None = Field(None , description='filter chats that contain any of specified strings (case-insensitive, comma-separated). Note: a string containing a whitespace will be matched as exact substring without being split to words.')
    phone: str | None = Field(None , description="Filter direct (non-group) chats by a single phone number. Phone is sanitized in the same way as for sending messages. If sanitized value starts with '+', the match is exact. Otherwise, leading zeroes are removed and the number is matched as a substring of the stored phone. Group chats are always excluded when this parameter is used.")
    read: bool | None = Field(None , description='filter chats that are either read (true) or unread (false)')
    closed: bool | None = Field(None , description='filter chats that are either closed (true) or open (false)')
    chatgpt_autoresponse_enabled: bool | None = Field(None , description='filter chats where chatgpt auto-response is enabled (true) or disabled (false)')
    page: int | None = Field(None , ge=1, description='specify the page of results (each page contains up to 50 items), starting with 1. Check \\"has more page" response value to see if more pages are available.')
    created_after: datetime | None = Field(None , description='filter chats that were created after this timestamp, can be specified with created_before')
    created_before: datetime | None = Field(None , description='filter chats that were created before this timestamp, can be specified with created_after')
    whatsapp_phone: str | None = Field(None , description="Filter chats by contact phone number(s) (comma-separated). Each number is matched both against the direct chat's phone (tolerating a leading `0` in place of the country code, or an already-international number) and against group membership, so groups containing a matching member are included too.")
    with_msg: bool | None = Field(None , description='when true, include the full last_message object (in addition to last_message_uid / last_message_timestamp) for each chat.')

class GetChat(Input):
    """Get details of a chat."""
    operation: Literal["get_chat"] = "get_chat"
    chat_id: int = Field(... , ge=1, description='an id of the chat as appears in TimelinesAI (can be found in the URL of the chat page, or in the payload of outbound webhook). _Supports sending messages to a group._')

class UpdateChat(Input):
    unassign_responsible: bool = Field(False, description="Unassign the responsible teammate; sends an empty responsible string.")
    """Update chat."""
    operation: Literal["update_chat"] = "update_chat"
    chat_id: int = Field(... , ge=1, description='an id of the chat as appears in TimelinesAI (can be found in the URL of the chat page, or in the payload of outbound webhook). _Supports sending messages to a group._')
    name: str | None = Field(None , max_length=256, description="Chat's name (must be unique in workspace)")
    responsible: str | None = Field(None , description='Assign team member as responsible (specified by registration email in TimelinesAI) or unassign a chat from responsible by supplying an empty string ("").')
    closed: bool | None = Field(None , description='Is the chart closed (true) or open (false)')
    read: bool | None = Field(None , description='Is the chat read (true) or unread (false)')
    chatgpt_autoresponse_enabled: bool | None = Field(None , description='Set the AI Agent (ChatGPT autoresponse) on or off for this chat. Setting `true` mirrors the in-app **AI Agent** switch — it clears any "auto-disabled by outgoing response" lock and re-arms the agent so it will reply to the next inbound message. Setting `false` turns the agent off for this chat.\n')

class ListChatMessages(Input):
    """Get filtered chat history (messages only) of the chat."""
    operation: Literal["list_chat_messages"] = "list_chat_messages"
    chat_id: int = Field(... , ge=1, description='an id of the chat as appears in TimelinesAI (can be found in the URL of the chat page, or in the payload of outbound webhook). _Supports sending messages to a group._')
    from_me: bool | None = Field(None , description='specify true to filter messages sent from my WhatsApp account (from any session), false to filter messages received from other WhatsApp users.')
    after: str | None = Field(None , description='can specify date or datetime in ISO format to filter out messages created AFTER the specified date (inclusive)')
    before: str | None = Field(None , description='can specify date or datetime in ISO format to filter out messages created BEFORE the specified date (inclusive)')
    after_message: str | None = Field(None , description='can specify message uid to filter out messages created after the specified message (excluding the specified message itself)')
    before_message: str | None = Field(None , description='can specify message uid to filter out messages created before the specified message (excluding the specified message itself)')
    sorting_order: Literal['asc', 'desc'] | None = Field(None , description='order messages by timestamp, according to possible values: asc, desc')

class SendChatMessage(Input):
    """Send message in existing chat."""
    operation: Literal["send_chat_message"] = "send_chat_message"
    chat_id: int = Field(... , ge=1, description='an id of the chat as appears in TimelinesAI (can be found in the URL of the chat page, or in the payload of outbound webhook). _Supports sending messages to a group._')
    reply_to: str | None = Field(None , description='UID of the message this message replies to. Must reference a message in the same workspace and WhatsApp account. Null or empty string is ignored.\n')
    text: str | None = Field(None , max_length=2000, description='plain text message')
    file_uid: str | None = Field(None , description='attachment UID')
    label: str | None = Field(None , max_length=64)
    chat_name: str | None = Field(None , max_length=256, description='an exact name of the chat (or group) as appears in TimelinesAI)')
    attachment_template_id: int | None = Field(None , description='a template ID of the attachment to be sent. The template must be created in the workspace before sending a message with it.')

    @model_validator(mode="after")
    def message_content(self):
        if not (self.text or self.file_uid or self.attachment_template_id):
            raise ValueError("Supply message text or an attachment")
        return self

class ListChatLabels(Input):
    """List labels for the specified chat."""
    operation: Literal["list_chat_labels"] = "list_chat_labels"
    chat_id: int = Field(... , ge=1, description='an id of the chat as appears in TimelinesAI (can be found in the URL of the chat page, or in the payload of outbound webhook). _Supports sending messages to a group._')

class ReplaceChatLabels(Input):
    """Replaces labels for the chat."""
    operation: Literal["replace_chat_labels"] = "replace_chat_labels"
    chat_id: int = Field(... , ge=1, description='an id of the chat as appears in TimelinesAI (can be found in the URL of the chat page, or in the payload of outbound webhook). _Supports sending messages to a group._')
    labels: list[Annotated[str, Field(max_length=64)]] = Field(... , description='Label names to apply. Each item must be a string up to 64 characters. Missing workspace labels are created automatically by label-apply endpoints.\n')

class AddChatLabels(Input):
    """Adds labels for the chat."""
    operation: Literal["add_chat_labels"] = "add_chat_labels"
    chat_id: int = Field(... , ge=1, description='an id of the chat as appears in TimelinesAI (can be found in the URL of the chat page, or in the payload of outbound webhook). _Supports sending messages to a group._')
    labels: list[Annotated[str, Field(max_length=64)]] = Field(... , description='Label names to apply. Each item must be a string up to 64 characters. Missing workspace labels are created automatically by label-apply endpoints.\n')

class AddChatNote(Input):
    """Add a note to existing chat."""
    operation: Literal["add_chat_note"] = "add_chat_note"
    chat_id: int = Field(... , ge=1, description='an id of the chat as appears in TimelinesAI (can be found in the URL of the chat page, or in the payload of outbound webhook). _Supports sending messages to a group._')
    text: str = Field(... , max_length=10000, description='plain text (will be displayed "as is", no additional processing will be made)')
    is_private: bool = Field(True , description='specify whether to set the note as public or private')

class GetMessage(Input):
    """Get the details of a message specified by the message's UID."""
    operation: Literal["get_message"] = "get_message"
    message_uid: str = Field(... , min_length=1, max_length=256, description='a UID of a message, that is unique for TimelinesAI workspace. Can be used to lookup a message or its sending status.')

class GetMessageStatusHistory(Input):
    """Get the sending history of a message, specified by the message's UID."""
    operation: Literal["get_message_status_history"] = "get_message_status_history"
    message_uid: str = Field(... , min_length=1, max_length=256, description='a UID of a message, that is unique for TimelinesAI workspace. Can be used to lookup a message or its sending status.')

class SendMessageToPhone(Input):
    """Send message to phone number."""
    operation: Literal["send_message_to_phone"] = "send_message_to_phone"
    phone: str = Field(... , description='a phone number, formatted according to international phone number standard, i.e.: [+][country code][area code][local phone number]')
    whatsapp_account_phone: str | None = Field(None , description='the WhatsApp account (as a phone number, in international format) to which the chat specified by JID belongs to. If omitted, the most recently connected WhatsApp account in the workspace will be used.')
    text: str | None = Field(None , max_length=2000, description='plain text message')
    file_uid: str | None = Field(None , description='attachment UID')
    label: str | None = Field(None , max_length=64)
    chat_name: str | None = Field(None , max_length=256, description='an exact name of the chat (or group) as appears in TimelinesAI)')
    attachment_template_id: int | None = Field(None , description='a template ID of the attachment to be sent. The template must be created in the workspace before sending a message with it.')

    @model_validator(mode="after")
    def message_content(self):
        if not (self.text or self.file_uid or self.attachment_template_id):
            raise ValueError("Supply message text or an attachment")
        return self

class ListFiles(Input):
    """List files uploaded in your TimelinesAI workspace."""
    operation: Literal["list_files"] = "list_files"
    filename: str | None = Field(None , description='a filename or any part of it (for example, extension), case insensitive . Leave empty to get unfiltered list of all uploaded files.')

class UploadFileFromUrl(Input):
    """Upload a file using a publicly accessible URL."""
    operation: Literal["upload_file_from_url"] = "upload_file_from_url"
    download_url: str = Field(... , description='A publicly accessible URL for the file (excluding download URLs from services like Google Drive or OneDrive).')
    filename: str | None = Field(None , max_length=1024, description='(optional) A filename, to be used instead of the original filename specified by the download URL.')
    content_type: str | None = Field(None , max_length=140, description='(optional) A mime-type of the file, to be used instead of the original filename specified by the download URL.')

class GetFile(Input):
    """Get details and temporary download URL for a specified uploaded file."""
    operation: Literal["get_file"] = "get_file"
    file_uid: str = Field(... , min_length=1, max_length=256, description='A UID for an uploaded file, unique within the TimelinesAI workspace, which can be used to reference the file in Public API methods for sending messages with attachments.')

class DeleteFile(Input):
    """Delete the specified uploaded file."""
    operation: Literal["delete_file"] = "delete_file"
    file_uid: str = Field(... , min_length=1, max_length=256, description='A UID for an uploaded file, unique within the TimelinesAI workspace, which can be used to reference the file in Public API methods for sending messages with attachments.')

class ListWhatsappAccounts(Input):
    """List WhatsApp accounts connected in your TimelinesAI workspace."""
    operation: Literal["list_whatsapp_accounts"] = "list_whatsapp_accounts"

class GetWorkspace(Input):
    """Workspace info and all current quotas and utilization stats."""
    operation: Literal["get_workspace"] = "get_workspace"

class ListTeammates(Input):
    """List all teammates in the workspace."""
    operation: Literal["list_teammates"] = "list_teammates"

class GetCurrentTeammate(Input):
    """Info about current teammate in the workspace."""
    operation: Literal["get_current_teammate"] = "get_current_teammate"

class ListTemplates(Input):
    """List templates."""
    operation: Literal["list_templates"] = "list_templates"

class CreateTemplate(Input):
    """Create template."""
    operation: Literal["create_template"] = "create_template"
    name: str = Field(... , max_length=160, min_length=1)
    text: str = Field(... , max_length=4096, min_length=1)
    visibility: Literal["public", "private", "read-only"] = "public"
    team_title: str | None = Field(None , description='Title of the team to share the template with. Omit for "all teams". Without `MANAGE_ALL_TEMPLATES`, the template is forced into the caller\'s own team regardless of this value. Valid values match the team titles returned by `GET /workspace/teammates`.')

class GetTemplate(Input):
    """Get template."""
    operation: Literal["get_template"] = "get_template"
    template_id: int = Field(... , ge=1, description='an ID of the template')

Operation = Annotated[Union[ListChats, GetChat, UpdateChat, ListChatMessages, SendChatMessage, ListChatLabels, ReplaceChatLabels, AddChatLabels, AddChatNote, GetMessage, GetMessageStatusHistory, SendMessageToPhone, ListFiles, UploadFileFromUrl, GetFile, DeleteFile, ListWhatsappAccounts, GetWorkspace, ListTeammates, GetCurrentTeammate, ListTemplates, CreateTemplate, GetTemplate], Field(discriminator="operation")]

class TimelinesAIFullConfig(NodeConfig):
    config: Operation
    credentials: TimelinesAIAPITokenCredential | None = None

ROUTES = {'list_chats': ('GET', '/chats', [], ['label', 'whatsapp_account_id', 'group', 'responsible', 'name', 'phone', 'read', 'closed', 'chatgpt_autoresponse_enabled', 'page', 'created_after', 'created_before', 'whatsapp_phone', 'with_msg'], []), 'get_chat': ('GET', '/chats/{chat_id}', ['chat_id'], [], []), 'update_chat': ('PATCH', '/chats/{chat_id}', ['chat_id'], [], ['name', 'responsible', 'closed', 'read', 'chatgpt_autoresponse_enabled']), 'list_chat_messages': ('GET', '/chats/{chat_id}/messages', ['chat_id'], ['from_me', 'after', 'before', 'after_message', 'before_message', 'sorting_order'], []), 'send_chat_message': ('POST', '/chats/{chat_id}/messages', ['chat_id'], [], ['reply_to', 'text', 'file_uid', 'label', 'chat_name', 'attachment_template_id']), 'list_chat_labels': ('GET', '/chats/{chat_id}/labels', ['chat_id'], [], []), 'replace_chat_labels': ('POST', '/chats/{chat_id}/labels', ['chat_id'], [], ['labels']), 'add_chat_labels': ('PUT', '/chats/{chat_id}/labels', ['chat_id'], [], ['labels']), 'add_chat_note': ('POST', '/chats/{chat_id}/notes', ['chat_id'], [], ['text', 'is_private']), 'get_message': ('GET', '/messages/{message_uid}', ['message_uid'], [], []), 'get_message_status_history': ('GET', '/messages/{message_uid}/status_history', ['message_uid'], [], []), 'send_message_to_phone': ('POST', '/messages', [], [], ['phone', 'whatsapp_account_phone', 'text', 'file_uid', 'label', 'chat_name', 'attachment_template_id']), 'list_files': ('GET', '/files', [], ['filename'], []), 'upload_file_from_url': ('POST', '/files', [], [], ['download_url', 'filename', 'content_type']), 'get_file': ('GET', '/files/{file_uid}', ['file_uid'], [], []), 'delete_file': ('DELETE', '/files/{file_uid}', ['file_uid'], [], []), 'list_whatsapp_accounts': ('GET', '/whatsapp_accounts', [], [], []), 'get_workspace': ('GET', '/workspace', [], [], []), 'list_teammates': ('GET', '/workspace/teammates', [], [], []), 'get_current_teammate': ('GET', '/workspace/teammates/me', [], [], []), 'list_templates': ('GET', '/templates', [], [], []), 'create_template': ('POST', '/templates', [], [], ['name', 'text', 'visibility', 'team_title']), 'get_template': ('GET', '/templates/{template_id}', ['template_id'], [], [])}

class TimelinesAINode(WorkflowNode):
    integration_type = "automation-timelinesai"
    connection_evidence = ConnectionEvidence(noun="TimelinesAI teammate", identity_operation="get_current_teammate")

    @classmethod
    def get_config_model(cls):
        return TimelinesAIFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a TimelinesAI API token")
        op = self.config.config
        method, route, path_fields, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        for key in path_fields:
            route = route.replace("{" + key + "}", quote(str(values[key]), safe=""))
        params = {k: str(values[k]).lower() if isinstance(values[k], bool) else values[k]
                  for k in query_fields if k in values}
        body = {k: values[k] for k in body_fields if k in values}
        if op.operation == "update_chat" and op.unassign_responsible:
            if op.responsible:
                raise ValueError("Choose a responsible teammate or unassign, not both")
            body["responsible"] = ""
        token = self.config.credentials.api_token
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + route,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if body_fields else {}))
        # Preserve the provider's rejection text for the shared connect verdict.
        if response.is_error:
            raise ValueError("TimelinesAI HTTP " + str(response.status_code) + ": " + response.text.replace(token, "[redacted]")[:2000])
        if op.operation == "delete_file" and not response.content:
            return {"status": "ok", "deleted_file_uid": op.file_uid}
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("TimelinesAI returned an unexpected response envelope")
        if payload.get("status") == "error":
            raise ValueError(str(payload).replace(token, "[redacted]")[:2000])
        return payload
