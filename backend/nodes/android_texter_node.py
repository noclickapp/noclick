"""Android Texter API v1.0.0; one published API operation per node operation.

Contract: https://androidtexter.com/api/openapi.json
Pagination is explicit: paginated reads return one provider page, unmodified.
Writes are never retried automatically (SMS delivery is not idempotent).
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://androidtexter.com/api"
CREDENTIAL_TYPE = "android_texter_api_key"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class AndroidTexterApiKeyCredential(_Input):
    model_config = ConfigDict(
        title="Android Texter API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://androidtexter.com/dashboard/settings/api-keys",
            "x-credential-instructions": "Create an API key in Android Texter under Dashboard → Settings → API Keys. Paste the key here; NoClick sends it in the X-API-Key header.",
        },
    )
    credential_type: Literal["android_texter_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False,
        description="Paste your Android Texter API key, without a header name or Bearer prefix.",
        json_schema_extra={"ui:widget": "password"})


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page", description="One-based page number. Each run fetches one page.")
    limit: int = Field(50, ge=1, le=100, title="Page Size")


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current User", json_schema_extra={"ui:hidden": True})


class ListDevices(_Input):
    operation: Literal["list_devices"] = Field("list_devices", title="List Linked Devices", json_schema_extra={"ui:hidden": True})


class GetDevice(_Input):
    operation: Literal["get_device"] = Field("get_device", title="Get Device", json_schema_extra={"ui:hidden": True})
    device_id: str = Field(..., min_length=1, title="Device ID")


class SendMessage(_Input):
    operation: Literal["send_message"] = Field("send_message", title="Send SMS or MMS", description="Queues a message through a linked Android phone. A successful response confirms queueing, not delivery. Optional scheduling uses an ISO 8601 timestamp.", json_schema_extra={"ui:hidden": True})
    phone: str = Field(..., min_length=1, title="Recipient Phone")
    message: str = Field(..., min_length=1, max_length=1600, title="Message")
    country: str | None = Field(None, title="Country", description="ISO 3166-1 alpha-2 country for local-format phone numbers; omitted uses the sending SIM's country.")
    device_id: str | None = Field(None, title="Device ID", description="Omitted selects the first online device.")
    media_url: str | None = Field(None, title="Media URL", description="Include a media URL to send MMS.")
    scheduled_at: str | None = Field(None, title="Scheduled At", description="ISO 8601 timestamp for a future send; omitted sends immediately.")
    sim_slot: int | None = Field(None, ge=0, le=1, title="SIM Slot", description="Dual-SIM phones: 0 for SIM 1, 1 for SIM 2. Omitted lets the phone decide.")
    thread_id: str | None = Field(None, title="Group Thread ID")


class SendBroadcast(_Input):
    operation: Literal["send_broadcast"] = Field("send_broadcast", title="Send Broadcast", description="Sends the same SMS or MMS to up to 500 recipients. Inspect each result and the failed count; HTTP success can include failed recipients.", json_schema_extra={"ui:hidden": True})
    phones: list[str] = Field(..., min_length=1, max_length=500, title="Recipient Phones")
    message: str = Field(..., min_length=1, max_length=1600, title="Message")
    media_url: str | None = Field(None, title="Media URL")
    device_id: str | None = Field(None, title="Device ID")
    device_mode: Literal["auto", "specific", "round-robin"] = Field("auto", title="Device Selection")

    @model_validator(mode="after")
    def specific_device(self):
        if self.device_mode == "specific" and not self.device_id:
            raise ValueError("Device ID is required for specific device selection")
        if any(not phone.strip() for phone in self.phones):
            raise ValueError("Recipient phone numbers must not be blank")
        return self


class _MessageID(_Input):
    message_id: str = Field(..., min_length=1, title="Message ID")


class GetMessageStatus(_MessageID):
    operation: Literal["get_message_status"] = Field("get_message_status", title="Get Message Delivery Status", json_schema_extra={"ui:hidden": True})


class GetConversationHistory(_Page):
    operation: Literal["get_conversation_history"] = Field("get_conversation_history", title="Get Conversation History", json_schema_extra={"ui:hidden": True})
    phone: str = Field(..., min_length=1, title="Phone")
    thread_id: str | None = Field(None, title="Group Thread ID")
    thread_ref: str | None = Field(None, title="Conversation Reference", description="Preferred over thread_id when both are known.")


class ListReceivedMessages(_Page):
    operation: Literal["list_received_messages"] = Field("list_received_messages", title="List Received Messages", json_schema_extra={"ui:hidden": True})


class ListConversations(_Input):
    operation: Literal["list_conversations"] = Field("list_conversations", title="List Conversations", json_schema_extra={"ui:hidden": True})
    view: Literal["inbox", "outbox", "archived", "spam", "all"] = Field("inbox", title="Folder")
    limit: int = Field(50, ge=1, le=2000, title="Limit", description="Maximum conversations returned, newest activity first.")


class _Conversation(_Input):
    thread_ref: str = Field(..., min_length=1, title="Conversation Reference", description="Copy the conversation ID returned by List Conversations.")


class ArchiveConversation(_Conversation):
    operation: Literal["archive_conversation"] = Field("archive_conversation", title="Archive or Unarchive Conversation", description="Incoming messages automatically unarchive the conversation.", json_schema_extra={"ui:hidden": True})
    archived: bool = Field(True, title="Archive", description="False moves the conversation out of Archived.")


class DeleteConversation(_Conversation):
    operation: Literal["delete_conversation"] = Field("delete_conversation", title="Delete Conversation Permanently", description="Deletes all conversation messages and tells every linked phone to delete its copy. Cannot be reversed; repeating the delete returns 404.", json_schema_extra={"ui:hidden": True})


class ListScheduledMessages(_Input):
    operation: Literal["list_scheduled_messages"] = Field("list_scheduled_messages", title="List Scheduled Messages", json_schema_extra={"ui:hidden": True})


class CancelScheduledMessage(_MessageID):
    operation: Literal["cancel_scheduled_message"] = Field("cancel_scheduled_message", title="Cancel Scheduled Message", json_schema_extra={"ui:hidden": True})


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, title="Search", description="Substring of contact name or phone.")
    tag: str | None = Field(None, title="Tag")


class UpsertContact(_Input):
    operation: Literal["upsert_contact"] = Field("upsert_contact", title="Create or Update Contact", description="Upserts by phone number and merges tags with existing tags.", json_schema_extra={"ui:hidden": True})
    phone: str = Field(..., min_length=1, title="Phone")
    name: str | None = Field(None, title="Name")
    company: str | None = Field(None, title="Company")
    email: str | None = Field(None, title="Email")
    notes: str | None = Field(None, title="Notes")
    tags: list[str] | None = Field(None, title="Tags")


class ListQuickReplies(_Input):
    operation: Literal["list_quick_replies"] = Field("list_quick_replies", title="List Quick Replies", json_schema_extra={"ui:hidden": True})


class _QuickReply(_Input):
    shortcut: str = Field(..., min_length=1, title="Shortcut", description="Must be unique within the account.")
    title: str = Field(..., min_length=1, title="Title")
    body: str = Field(..., min_length=1, title="Reply Text")


class CreateQuickReply(_QuickReply):
    operation: Literal["create_quick_reply"] = Field("create_quick_reply", title="Create Quick Reply", json_schema_extra={"ui:hidden": True})


class _QuickReplyID(_Input):
    quick_reply_id: str = Field(..., min_length=1, title="Quick Reply ID")


class UpdateQuickReply(_QuickReply, _QuickReplyID):
    operation: Literal["update_quick_reply"] = Field("update_quick_reply", title="Update Quick Reply", json_schema_extra={"ui:hidden": True})


class DeleteQuickReply(_QuickReplyID):
    operation: Literal["delete_quick_reply"] = Field("delete_quick_reply", title="Delete Quick Reply", json_schema_extra={"ui:hidden": True})


class _SpamPhone(_Input):
    phone: str = Field(..., min_length=1, title="Phone")
    country: str | None = Field(None, title="Country", description="ISO 3166-1 alpha-2 country for a local-format phone number.")


class FlagSpam(_SpamPhone):
    operation: Literal["flag_spam"] = Field("flag_spam", title="Flag Phone as Spam", description="Hides the conversation and suppresses notifications. If default_spam_live_mode is enabled on the account, also starts its AI evidence-collection agent; engaged in the response reports this.", json_schema_extra={"ui:hidden": True})


class UnflagSpam(_SpamPhone):
    operation: Literal["unflag_spam"] = Field("unflag_spam", title="Remove Phone from Spam", description="Leaves any active AI engagement on the phone as-is.", json_schema_extra={"ui:hidden": True})


class ListSpamThreads(_Input):
    operation: Literal["list_spam_threads"] = Field("list_spam_threads", title="List Spam Phones", json_schema_extra={"ui:hidden": True})


class ListWebhooks(_Input):
    operation: Literal["list_webhooks"] = Field("list_webhooks", title="List Webhooks", json_schema_extra={"ui:hidden": True})


class CreateWebhook(_Input):
    operation: Literal["create_webhook"] = Field("create_webhook", title="Register Webhook", description="The response includes a signing secret shown only once. Store it to verify incoming delivery signatures. This action registers a subscription; it does not create a NoClick trigger.", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, title="Delivery URL")
    events: list[str] | None = Field(None, title="Events", description="Omitted subscribes to message.received and message.sent.")


class DeleteWebhook(_Input):
    operation: Literal["delete_webhook"] = Field("delete_webhook", title="Delete Webhook", json_schema_extra={"ui:hidden": True})
    webhook_id: str = Field(..., min_length=1, title="Webhook ID")


Operation = Annotated[Union[
    GetCurrentUser, ListDevices, GetDevice, SendMessage, SendBroadcast,
    GetMessageStatus, GetConversationHistory, ListReceivedMessages,
    ListConversations, ArchiveConversation, DeleteConversation,
    ListScheduledMessages, CancelScheduledMessage, ListContacts, UpsertContact,
    ListQuickReplies, CreateQuickReply, UpdateQuickReply, DeleteQuickReply,
    FlagSpam, UnflagSpam, ListSpamThreads, ListWebhooks, CreateWebhook, DeleteWebhook,
], Field(discriminator="operation")]


class AndroidTexterNodeConfig(NodeConfig[Operation, AndroidTexterApiKeyCredential]):
    pass


# method, contract path, config path field, query fields, JSON body fields, status
ROUTES = {
    "get_current_user": ("GET", "/me", None, (), (), 200),
    "list_devices": ("GET", "/v1/devices", None, (), (), 200),
    "get_device": ("GET", "/devices/{id}", "device_id", (), (), 200),
    "send_message": ("POST", "/v1/messages/send", None, (), ("phone", "message", "country", "device_id", "media_url", "scheduled_at", "sim_slot", "thread_id"), 200),
    "send_broadcast": ("POST", "/messages/broadcast", None, (), ("phones", "message", "media_url", "device_id", "device_mode"), 200),
    "get_message_status": ("GET", "/v1/messages/status/{id}", "message_id", (), (), 200),
    "get_conversation_history": ("GET", "/v1/messages/history/{phone}", "phone", ("page", "limit", "thread_id", "thread_ref"), (), 200),
    "list_received_messages": ("GET", "/messages/received", None, ("page", "limit"), (), 200),
    "list_conversations": ("GET", "/messages/conversations", None, ("view", "limit"), (), 200),
    "archive_conversation": ("POST", "/messages/conversations/archive", None, ("thread_ref", "archived"), (), 200),
    "delete_conversation": ("DELETE", "/v1/messages/thread", None, ("thread_ref",), (), 200),
    "list_scheduled_messages": ("GET", "/messages/scheduled", None, (), (), 200),
    "cancel_scheduled_message": ("DELETE", "/messages/scheduled/{id}", "message_id", (), (), 200),
    "list_contacts": ("GET", "/contacts", None, ("page", "limit", "search", "tag"), (), 200),
    "upsert_contact": ("POST", "/contacts", None, (), ("phone", "name", "company", "email", "notes", "tags"), 201),
    "list_quick_replies": ("GET", "/quick-replies", None, (), (), 200),
    "create_quick_reply": ("POST", "/quick-replies", None, (), ("shortcut", "title", "body"), 201),
    "update_quick_reply": ("PUT", "/quick-replies/{id}", "quick_reply_id", (), ("shortcut", "title", "body"), 200),
    "delete_quick_reply": ("DELETE", "/quick-replies/{id}", "quick_reply_id", (), (), 200),
    "flag_spam": ("POST", "/spam/flag", None, (), ("phone", "country"), 200),
    "unflag_spam": ("POST", "/spam/unflag", None, (), ("phone", "country"), 200),
    "list_spam_threads": ("GET", "/spam/threads", None, (), (), 200),
    "list_webhooks": ("GET", "/webhooks", None, (), (), 200),
    "create_webhook": ("POST", "/v1/webhooks", None, (), ("url", "events"), 201),
    "delete_webhook": ("DELETE", "/v1/webhooks/{id}", "webhook_id", (), (), 200),
}


class AndroidTexterNode(WorkflowNode):
    integration_type = "automation-android-texter"
    connection_evidence = ConnectionEvidence(noun="linked Android devices", operation="list_devices", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return AndroidTexterNodeConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Android Texter API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route, path_field, query_fields, body_fields, expected = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        if path_field:
            value = str(values[path_field])
            if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
                raise ValueError("Use a single resource ID or phone number")
            route = route.replace("{phone}" if path_field == "phone" else "{id}", quote(value, safe=""))
        params = {field: values[field] for field in query_fields if field in values}
        body = {field: values[field] for field in body_fields if field in values}
        output = {"operation": config.operation}
        http_status = None
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, BASE_URL + route,
                    headers={"X-API-Key": key, "Accept": "application/json"},
                    params=params, **({"json": body} if body_fields else {})) as response:
                    http_status = response.status_code
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError("Android Texter response exceeds 8 MiB")
                    try:
                        data = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ValueError("Android Texter returned a non-JSON response") from None
                    if not isinstance(data, dict):
                        raise ValueError("Android Texter returned an unexpected response shape")
                    if http_status != expected or data.get("error") or data.get("success") is False:
                        message = data.get("error") or data.get("message") or f"Android Texter returned HTTP {http_status}"
                        raise ValueError(str(message).replace(key, "[redacted]"))
            return {**output, "status": "success", "data": data}
        except (httpx.HTTPError, SSRFError, OSError):
            return {**output, "status": "error", "http_status": http_status,
                "error": "Android Texter request did not complete. Inspect message status before retrying a send."}
        except ValueError as exc:
            return {**output, "status": "error", "http_status": http_status, "error": str(exc).replace(key, "[redacted]")}
