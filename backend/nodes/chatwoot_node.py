"""Chatwoot Application API: contacts, conversations, routing and replies.

Reference: https://developers.chatwoot.com/api-reference/introduction
Uses a user API token from Profile Settings. Each operation makes one documented
request; list operations return one provider page, including its metadata.
"""

import hashlib
import hmac
import json
import time
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import assert_url_allowed, normalize_https_origin


def operation(value: str, title: str, category: str):
    return Field(value, title=title, json_schema_extra={
        "const": value, "ui:hidden": True, "x-display-name": title,
        "x-category": category, "x-is-trigger": False,
    })


def inbox_field(required=True):
    return Field(... if required else None, gt=0, title="Inbox", json_schema_extra={
        "x-dynamic-options": {"field_name": "inbox_id", "allow_custom": True},
    })


def json_field(title: str, description: str):
    return Field(None, title=title, description=description, json_schema_extra={"ui:widget": "textarea"})


class ChatwootAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Chatwoot API Token", json_schema_extra={
        "x-credential-url": "https://developers.chatwoot.com/api-reference/introduction",
        "x-credential-instructions": "In Chatwoot, open Profile Settings and copy your API access token. Enter the account ID from your /app/accounts/<id> URL. Use https://app.chatwoot.com for Chatwoot Cloud, or your self-hosted HTTPS origin. The token uses your user's permissions; routing and account lists may require an administrator.",
    })
    credential_type: Literal["chatwoot_api_token"] = Field("chatwoot_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    account_id: int = Field(..., title="Account ID", gt=0)
    base_url: str = Field("https://app.chatwoot.com", title="Chatwoot URL", description="Exact HTTPS origin of Chatwoot Cloud or your self-hosted instance.")

    @field_validator("base_url")
    @classmethod
    def validate_origin(cls, value):
        return normalize_https_origin(value, field_name="Chatwoot URL")


class GetProfile(BaseModel):
    operation: Literal["get_profile"] = operation("get_profile", "Get User Profile", "Account")


class ListInboxes(BaseModel):
    operation: Literal["list_inboxes"] = operation("list_inboxes", "List Inboxes", "Account")


class ListAgents(BaseModel):
    operation: Literal["list_agents"] = operation("list_agents", "List Agents", "Account")


class ListTeams(BaseModel):
    operation: Literal["list_teams"] = operation("list_teams", "List Teams", "Account")


class ContactPage(BaseModel):
    page: int = Field(1, ge=1, title="Page", description="One page per call; Chatwoot returns 15 contacts per page.")
    sort: str | None = Field(None, title="Sort", description="Optional documented contact sort, such as name or -name.")


class ListContacts(ContactPage):
    operation: Literal["list_contacts"] = operation("list_contacts", "List Contacts", "Contacts")


class SearchContacts(ContactPage):
    operation: Literal["search_contacts"] = operation("search_contacts", "Search Contacts", "Contacts")
    query: str = Field(..., min_length=1, title="Search", description="Search resolved contacts by email.")


class ContactID(BaseModel):
    contact_id: int = Field(..., gt=0, title="Contact ID")


class GetContact(ContactID):
    operation: Literal["get_contact"] = operation("get_contact", "Get Contact", "Contacts")


class ContactFields(BaseModel):
    name: str | None = Field(None, title="Name")
    email: str | None = Field(None, title="Email")
    phone_number: str | None = Field(None, title="Phone Number", description="Include the country code, for example +123456789.")
    identifier: str | None = Field(None, title="External Identifier")
    blocked: bool | None = Field(None, title="Blocked")
    avatar_url: str | None = Field(None, title="Avatar URL")
    additional_attributes: str | None = json_field("Additional Attributes", "JSON object of additional contact attributes.")
    custom_attributes: str | None = json_field("Custom Attributes", "JSON object using existing Chatwoot custom attribute definitions.")


class CreateContact(ContactFields):
    operation: Literal["create_contact"] = operation("create_contact", "Create Contact", "Contacts")
    inbox_id: int = inbox_field()


class UpdateContact(ContactFields, ContactID):
    operation: Literal["update_contact"] = operation("update_contact", "Update Contact", "Contacts")

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, key) is not None for key in ContactFields.model_fields):
            raise ValueError("Supply at least one contact field to update")
        return self


class ListContactConversations(ContactID):
    operation: Literal["list_contact_conversations"] = operation("list_contact_conversations", "List Contact Conversations", "Contacts")


class ListConversations(BaseModel):
    operation: Literal["list_conversations"] = operation("list_conversations", "List Conversations", "Conversations")
    page: int = Field(1, ge=1, title="Page", description="Return one provider page.")
    status: Literal["all", "open", "resolved", "pending", "snoozed"] = Field("open", title="Status")
    assignee_type: Literal["me", "unassigned", "all", "assigned"] = Field("all", title="Assignee Type")
    inbox_id: int | None = inbox_field(False)
    team_id: int | None = Field(None, gt=0, title="Team ID")
    query: str | None = Field(None, title="Search")


class ConversationID(BaseModel):
    conversation_id: int = Field(..., gt=0, title="Conversation ID")


class GetConversation(ConversationID):
    operation: Literal["get_conversation"] = operation("get_conversation", "Get Conversation", "Conversations")


class CreateConversation(BaseModel):
    operation: Literal["create_conversation"] = operation("create_conversation", "Create Conversation", "Conversations")
    source_id: str = Field(..., min_length=1, title="Source ID", description="Contact-inbox source_id from the contact's contact_inboxes, not the contact ID.")
    inbox_id: int = inbox_field()
    contact_id: int = Field(..., gt=0, title="Contact ID")
    status: Literal["open", "resolved", "pending"] = Field("open", title="Status")
    assignee_id: int | None = Field(None, gt=0, title="Assignee ID")
    team_id: int | None = Field(None, gt=0, title="Team ID")
    content: str | None = Field(None, title="Initial Message", json_schema_extra={"ui:widget": "textarea"})
    custom_attributes: str | None = json_field("Custom Attributes", "JSON object using existing conversation custom attribute definitions.")


class AssignConversation(ConversationID):
    operation: Literal["assign_conversation"] = operation("assign_conversation", "Assign Conversation", "Routing")
    assignee_id: int | None = Field(None, gt=0, title="Assignee ID", description="Agent ID. Takes precedence over team ID.")
    team_id: int | None = Field(None, gt=0, title="Team ID")

    @model_validator(mode="after")
    def has_target(self):
        if self.assignee_id is None and self.team_id is None:
            raise ValueError("Supply an assignee ID or team ID")
        return self


class SetConversationStatus(ConversationID):
    operation: Literal["set_conversation_status"] = operation("set_conversation_status", "Set Conversation Status", "Routing")
    status: Literal["open", "resolved", "pending", "snoozed"] = Field(..., title="Status")
    snoozed_until: int | None = Field(None, gt=0, title="Snoozed Until", description="Unix timestamp in seconds. With snoozed status, omit to snooze until the next customer reply.")

    @model_validator(mode="after")
    def snooze_only(self):
        if self.snoozed_until is not None and self.status != "snoozed":
            raise ValueError("Snoozed Until requires snoozed status")
        return self


class SetConversationPriority(ConversationID):
    operation: Literal["set_conversation_priority"] = operation("set_conversation_priority", "Set Conversation Priority", "Routing")
    priority: Literal["urgent", "high", "medium", "low", "clear"] = Field(..., title="Priority", description="Clear sends null to remove the priority.")


class ListConversationLabels(ConversationID):
    operation: Literal["list_conversation_labels"] = operation("list_conversation_labels", "List Conversation Labels", "Routing")


class SetConversationLabels(ConversationID):
    operation: Literal["set_conversation_labels"] = operation("set_conversation_labels", "Set Conversation Labels", "Routing")
    labels: str | list[str] = Field(..., title="Labels", description='JSON string array, e.g. ["support", "billing"]. Replaces all labels; [] clears them.', json_schema_extra={"ui:widget": "textarea"})


class ListMessages(ConversationID):
    operation: Literal["list_messages"] = operation("list_messages", "List Messages", "Messages")
    before: int | None = Field(None, gt=0, title="Before Message ID", description="Pagination cursor for older messages.")
    after: int | None = Field(None, gt=0, title="After Message ID", description="Pagination cursor for newer messages.")


class SendMessage(ConversationID):
    operation: Literal["send_message"] = operation("send_message", "Send Reply or Private Note", "Messages")
    content: str = Field(..., min_length=1, title="Message", json_schema_extra={"ui:widget": "textarea"})
    private: bool = Field(False, title="Private Note", description="Yes creates an internal note; No sends a public reply.")


class ChatwootWebhookConfig(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(
        None, title="Webhook URL", description="Registered with Chatwoot automatically. Requires an account administrator and a Chatwoot version that returns a webhook signing secret.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


def trigger_operation(value: str, title: str):
    return Field(value, title=title, json_schema_extra={
        "const": value, "ui:hidden": True, "x-display-name": title,
        "x-category": "Triggers", "x-is-trigger": True,
    })


class OnMessageCreated(ChatwootWebhookConfig):
    operation: Literal["on_message_created"] = trigger_operation("on_message_created", "On New Message")
    message_type: Literal["incoming", "outgoing", "all"] = Field(
        "incoming", title="Message Direction", description="Incoming customer messages by default. Choose all to include agent replies and template messages.")


class OnConversationCreated(ChatwootWebhookConfig):
    operation: Literal["on_conversation_created"] = trigger_operation("on_conversation_created", "On New Conversation")


class OnConversationStatusChanged(ChatwootWebhookConfig):
    operation: Literal["on_conversation_status_changed"] = trigger_operation("on_conversation_status_changed", "On Conversation Status Changed")


TRIGGER_EVENTS = {
    "on_message_created": "message_created",
    "on_conversation_created": "conversation_created",
    "on_conversation_status_changed": "conversation_status_changed",
}


ChatwootConfig = Annotated[Union[
    GetProfile, ListInboxes, ListAgents, ListTeams, ListContacts, SearchContacts,
    GetContact, CreateContact, UpdateContact, ListContactConversations,
    ListConversations, GetConversation, CreateConversation, AssignConversation,
    SetConversationStatus, SetConversationPriority, ListConversationLabels,
    SetConversationLabels, ListMessages, SendMessage,
    OnMessageCreated, OnConversationCreated, OnConversationStatusChanged,
], Discriminator("operation")]


class ChatwootNodeConfig(NodeConfig[ChatwootConfig, ChatwootAPITokenCredential]):
    pass


# One documented endpoint per operation. Keys not named here never reach the API.
# https://raw.githubusercontent.com/chatwoot/chatwoot/develop/swagger/tag_groups/application_swagger.json
ROUTES = {
    "get_profile": ("GET", "/api/v1/profile"),
    "list_inboxes": ("GET", "/inboxes"),
    "list_agents": ("GET", "/agents"),
    "list_teams": ("GET", "/teams"),
    "list_contacts": ("GET", "/contacts"),
    "search_contacts": ("GET", "/contacts/search"),
    "get_contact": ("GET", "/contacts/{contact_id}"),
    "create_contact": ("POST", "/contacts"),
    "update_contact": ("PUT", "/contacts/{contact_id}"),
    "list_contact_conversations": ("GET", "/contacts/{contact_id}/conversations"),
    "list_conversations": ("GET", "/conversations"),
    "get_conversation": ("GET", "/conversations/{conversation_id}"),
    "create_conversation": ("POST", "/conversations"),
    "assign_conversation": ("POST", "/conversations/{conversation_id}/assignments"),
    "set_conversation_status": ("POST", "/conversations/{conversation_id}/toggle_status"),
    "set_conversation_priority": ("PATCH", "/conversations/{conversation_id}"),
    "list_conversation_labels": ("GET", "/conversations/{conversation_id}/labels"),
    "set_conversation_labels": ("POST", "/conversations/{conversation_id}/labels"),
    "list_messages": ("GET", "/conversations/{conversation_id}/messages"),
    "send_message": ("POST", "/conversations/{conversation_id}/messages"),
}


def parse_json(value, kind, name):
    try:
        result = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be valid JSON") from exc
    if not isinstance(result, kind) or (kind is list and not all(isinstance(item, str) for item in result)):
        raise ValueError(f"{name} must be a JSON {'string array' if kind is list else 'object'}")
    return result


class ChatwootNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-chatwoot"
    connection_evidence = ConnectionEvidence(field="inbox_id", noun="inboxes", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return ChatwootNodeConfig

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        # https://developers.chatwoot.com/api-reference/webhooks/add-a-webhook
        event = TRIGGER_EVENTS.get((config or {}).get("operation"))
        if not event:
            raise ValueError("Choose a Chatwoot trigger before registering its webhook")
        credentials = ChatwootAPITokenCredential.model_validate(credential)
        path = f"/api/v1/accounts/{credentials.account_id}/webhooks"
        result = await cls.request(credentials, "POST", path, body={
            "url": webhook_url, "name": f"NoClick {node_id}", "subscriptions": [event],
        })
        if not isinstance(result, dict) or not result.get("id"):
            raise ValueError("Chatwoot did not return a webhook ID")
        if not result.get("secret"):
            # Older releases deliver unsigned webhooks. Remove the unusable
            # registration so retries do not leave orphan subscriptions.
            await cls.request(credentials, "DELETE", f"{path}/{int(result['id'])}")
            raise ValueError("Chatwoot did not return a signing secret; upgrade to a version with signed webhook delivery")
        return {"external_webhook_id": str(result["id"]), "signing_secret": result["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        # https://developers.chatwoot.com/api-reference/webhooks/delete-a-webhook
        external_id = (config or {}).get("external_webhook_id")
        if external_id is None or not credential:
            return
        credentials = ChatwootAPITokenCredential.model_validate(credential)
        await cls.request(credentials, "DELETE", f"/api/v1/accounts/{credentials.account_id}/webhooks/{int(external_id)}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        # https://www.chatwoot.com/hc/user-guide/articles/1677693021-how-to-use-webhooks
        secret = (config or {}).get("signing_secret")
        normalized = {key.lower(): value for key, value in headers.items()}
        timestamp = normalized.get("x-chatwoot-timestamp", "")
        signature = normalized.get("x-chatwoot-signature", "")
        if not secret or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = "sha256=" + hmac.new(str(secret).encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = TRIGGER_EVENTS.get((config or {}).get("operation"))
        if not event or payload.get("event") != event:
            return False
        if event == "message_created":
            direction = (config or {}).get("message_type", "incoming")
            return direction == "all" or payload.get("message_type") == direction
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        # The guide defines message attributes and conversation attributes
        # separately. Read only the fields documented for that event family.
        payload = output if "event" in output else output.get("data", {})
        event = payload.get("event")
        if event not in TRIGGER_EVENTS.values():
            return super().resolve_agent_event(output)
        if event == "message_created":
            sender = payload.get("sender") or {}
            conversation = payload.get("conversation") or {}
            account = payload.get("account") or {}
            # The guide's introductory example uses display_id; its expanded
            # Conversation attributes use id. Both are documented shapes.
            conversation_id = conversation["display_id"] if "display_id" in conversation else conversation.get("id")
            contact = payload["contact"] if "contact" in payload else (conversation.get("meta") or {}).get("sender") or {}
            account_id = account.get("id")
            actor = contact.get("name") or sender.get("name") or "Customer"
            lines = [f"Chatwoot new {payload.get('message_type')} message from {actor}:",
                     str(payload.get("content") or "(no text)"),
                     f"Message ID: {payload.get('id')}; contact ID: {contact.get('id')}; sender ID: {sender.get('id')}"]
        else:
            conversation_id = payload.get("id")
            account_id = payload.get("account_id")
            contact = (payload.get("meta") or {}).get("sender") or {}
            actor = contact.get("name") or "Customer"
            lines = [f"Chatwoot {event.replace('_', ' ')} for {actor}.",
                     f"Status: {payload.get('status')}; inbox ID: {payload.get('inbox_id')}; contact ID: {contact.get('id')}"]
        lines.append(f"Account ID: {account_id}; conversation ID: {conversation_id}")
        lines.append(f"To act: get_conversation or send_message with conversation_id={conversation_id}.")
        return {"text": "\n".join(lines), "conversation_key": f"chatwoot:{account_id}:{conversation_id}",
                "title": f"Chatwoot conversation {conversation_id}: {actor}"}

    @classmethod
    async def request(cls, credentials, method, path, *, params=None, body=None):
        url = credentials.base_url + path
        await assert_url_allowed(url)
        # Redirects stay disabled so a custom instance cannot forward the token.
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, headers={
                "api_access_token": credentials.api_token, "Accept": "application/json",
            }, params=params, json=body)
        if not 200 <= response.status_code < 300:
            detail = response.text.replace(credentials.api_token, "[redacted]")[:1000]
            raise ValueError(f"Chatwoot HTTP {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            return {}
        try:
            result = response.json()
        except ValueError as exc:
            raise ValueError("Chatwoot returned a non-JSON response; check the Chatwoot URL") from exc
        if not isinstance(result, (dict, list)):
            raise ValueError("Chatwoot returned an unexpected response shape")
        if isinstance(result, dict) and (result.get("error") or result.get("errors")):
            detail = json.dumps(result).replace(credentials.api_token, "[redacted]")[:1000]
            raise ValueError(f"Chatwoot: {detail}")
        return result

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None):
        if field_name != "inbox_id":
            return []
        credentials = ChatwootAPITokenCredential.model_validate(credential_data)
        result = await cls.request(credentials, "GET", f"/api/v1/accounts/{credentials.account_id}/inboxes")
        if not isinstance(result, dict) or not isinstance(result.get("payload"), list):
            raise ValueError("Chatwoot returned an unexpected inbox list")
        return [{"value": str(item["id"]), "label": item.get("name") or str(item["id"])} for item in result["payload"]]

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.config or not isinstance(self.config, ChatwootNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Chatwoot API token in the credentials tab")
        started = time.monotonic()
        config, credentials = self.config.config, self.config.credentials
        op = config.operation
        if op in TRIGGER_EVENTS:
            payload = inputs or self.node_data.get("config", {}).get("_triggerPayload") or {}
            if self.filter_trigger_payload(payload, config.model_dump()):
                return {"status": "success", "operation": op, "data": payload}
            return {"status": "no_event", "operation": op, "data": {}}
        method, route = ROUTES[op]
        values = config.model_dump(exclude_none=True)
        values.pop("operation")
        path = route.format(**values)
        if op != "get_profile":
            path = f"/api/v1/accounts/{credentials.account_id}" + path
        for key in ("contact_id", "conversation_id"):
            if "{" + key + "}" in route:
                values.pop(key)
        if "query" in values:
            values["q"] = values.pop("query")
        for key in ("additional_attributes", "custom_attributes", "labels"):
            if key in values:
                values[key] = parse_json(values[key], list if key == "labels" else dict, key)
        if op == "create_conversation" and "content" in values:
            values["message"] = {"content": values.pop("content")}
        if op == "set_conversation_priority" and values["priority"] == "clear":
            values["priority"] = None
        if op == "send_message":
            values.update(message_type="outgoing", content_type="text")
        result = await self.request(credentials, method, path,
                                    params=values if method == "GET" else None,
                                    body=values if method != "GET" else None)
        if op in {"list_conversation_labels", "set_conversation_labels"}:
            if not isinstance(result, dict) or not isinstance(result.get("payload"), list):
                raise ValueError("Chatwoot returned an unexpected label list")
            result = {"labels": [{"label": label} for label in result["payload"]]}
        # The profile endpoint includes issued tokens. Do not persist them as workflow output.
        if op == "get_profile" and isinstance(result, dict):
            result = {k: v for k, v in result.items() if k not in {"access_token", "pubsub_token", "hmac_identifier"}}
        return {"status": "success", "operation": op, "data": result,
                "timing_ms": {"request": round((time.monotonic() - started) * 1000, 2)}}
