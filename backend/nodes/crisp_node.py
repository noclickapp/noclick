"""Crisp (crisp.chat): answer website chats.

A visitor's message wakes the workflow, one agent thread per Crisp
conversation, and the conversation operations are the agent's tools: reply,
send a file, add a private note, read the thread, resolve it, assign it, look up
who is writing.

REST API v1 with the workspace's API token (website tier), which reaches that
one workspace and nothing else: https://docs.crisp.chat/references/rest-api/v1/.
Events come through NoClick's Crisp plugin (``utils/crisp_webhooks.py``).
"""

import os
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_subscriptions import AppEventTriggerMixin, RegistrationAdvisory
from utils.crisp_webhooks import HOOK_SECRET_ENV, PROVIDER, VISITOR_MESSAGE, sent_message_key
from utils.registration_verdict import RegistrationUnverified
from utils.self_echo import record_self_post

API_BASE = "https://api.crisp.chat/v1"
TRIGGER_OPERATION = "on_visitor_message"
# NoClick's Crisp plugin: its id and token tell whether a workspace installed it,
# and the install link is what a workspace that hasn't is shown.
PLUGIN_ID_ENV = "CRISP_PLUGIN_ID"
PLUGIN_IDENTIFIER_ENV = "CRISP_PLUGIN_TOKEN_IDENTIFIER"
PLUGIN_KEY_ENV = "CRISP_PLUGIN_TOKEN_KEY"
PLUGIN_INSTALL_URL_ENV = "CRISP_PLUGIN_INSTALL_URL"

UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
SESSION_PATTERN = r"^session_[0-9a-fA-F-]{36}$"


class CrispAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Crisp API Token", json_schema_extra={
        "x-credential-url": "https://docs.crisp.chat/guides/rest-api/authentication/website-token/",
        "x-credential-instructions": (
            "In Crisp, a workspace owner opens Settings → Workspace Settings → Advanced configuration → API Token "
            "and clicks Generate Token, then copies its Identifier and Key (Crisp shows the key once). If the "
            "workspace already has a token, use that one: generating a new one replaces it everywhere it's used. "
            "The Website ID is the CRISP_WEBSITE_ID in your chat widget's code. For chats to wake an agent, also "
            "add the NoClick plugin to the workspace (the trigger's status links it)."
        ),
    })
    credential_type: Literal["crisp_website_token"] = Field("crisp_website_token", json_schema_extra={"ui:hidden": True})
    website_id: str = Field(..., title="Website ID", pattern=UUID_PATTERN)
    identifier: str = Field(..., title="Token Identifier", min_length=1)
    key: str = Field(..., title="Token Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})


def operation(value: str, title: str, category: str):
    return Field(value, title=title, json_schema_extra={
        "const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False,
    })


def session_field():
    return Field(..., title="Session ID", pattern=SESSION_PATTERN,
                 description="The conversation's session_id (session_…), as the trigger and list_conversations give it.")


def sender_field():
    return Field(None, title="Sender Name", description="Name the visitor sees on the message. Empty: the workspace's.")


class Conversation(BaseModel):
    session_id: str = session_field()


class SendMessage(Conversation):
    """Reply to the visitor in a Crisp conversation, as the team."""
    operation: Literal["send_message"] = operation("send_message", "Send Message", "Messages")
    message: str = Field(..., min_length=1, title="Message", json_schema_extra={"ui:widget": "textarea"})
    sender_name: Optional[str] = sender_field()


class SendFile(Conversation):
    """Send the visitor a file in a Crisp conversation, from a public URL."""
    operation: Literal["send_file"] = operation("send_file", "Send File", "Messages")
    file_url: str = Field(..., title="File URL", pattern=r"^https://", description="Public HTTPS URL of the file.")
    file_name: str = Field(..., min_length=1, title="File Name", description="Shown to the visitor, e.g. invoice.pdf.")
    mime_type: str = Field(..., min_length=1, title="MIME Type", description="e.g. application/pdf or image/png.")
    sender_name: Optional[str] = sender_field()


class AddNote(Conversation):
    """Add a private note to a Crisp conversation: the team sees it in the inbox, the visitor never does."""
    operation: Literal["add_note"] = operation("add_note", "Add Private Note", "Messages")
    note: str = Field(..., min_length=1, title="Note", json_schema_extra={"ui:widget": "textarea"})


class GetMessages(Conversation):
    """Read a Crisp conversation's messages, the latest batch first; from "user" is the visitor, "operator" the team (and NoClick)."""
    operation: Literal["get_messages"] = operation("get_messages", "Get Messages", "Messages")
    before_timestamp: Optional[int] = Field(
        None, gt=0, title="Before Timestamp", description="Unix ms: return the batch before it, to page back through older messages.")


class ListConversations(BaseModel):
    """List or search the workspace's Crisp conversations, most recently active first."""
    operation: Literal["list_conversations"] = operation("list_conversations", "List Conversations", "Conversations")
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(20, ge=20, le=50, title="Per Page", description="20 to 50 conversations per page.")
    search: Optional[str] = Field(None, title="Search", description="Text to find in messages, names or emails.")
    status: Literal["all", "unresolved", "resolved"] = Field("all", title="Status")
    unread_only: Literal["true", "false"] = Field(
        "false", title="Unread Only", json_schema_extra={"enumNames": ["Yes", "No"], "x-enum-searchable": True})
    unassigned_only: Literal["true", "false"] = Field(
        "false", title="Unassigned Only", json_schema_extra={"enumNames": ["Yes", "No"], "x-enum-searchable": True})


class GetConversation(Conversation):
    """Get a Crisp conversation: its state, assignee, unread counts, last message and the visitor's details."""
    operation: Literal["get_conversation"] = operation("get_conversation", "Get Conversation", "Conversations")


class SetConversationState(Conversation):
    """Resolve a Crisp conversation, or reopen it as unresolved or pending."""
    operation: Literal["set_conversation_state"] = operation("set_conversation_state", "Set Conversation State", "Conversations")
    state: Literal["resolved", "unresolved", "pending"] = Field(..., title="State")


class AssignConversation(Conversation):
    """Assign a Crisp conversation to a teammate (an operator), e.g. to hand it to a human."""
    operation: Literal["assign_conversation"] = operation("assign_conversation", "Assign Conversation", "Conversations")
    operator_id: str = Field(..., title="Operator", pattern=UUID_PATTERN, json_schema_extra={
        "x-dynamic-options": {"field_name": "operator_id", "allow_custom": True},
    })


class ListOperators(BaseModel):
    """List the workspace's teammates (operators) with their user_id, name, role and availability."""
    operation: Literal["list_operators"] = operation("list_operators", "List Teammates", "Team")


class GetVisitor(Conversation):
    """Get who is writing in a Crisp conversation: name, email, phone, segments, custom data, location and device."""
    operation: Literal["get_visitor"] = operation("get_visitor", "Get Visitor Details", "Contacts")


class UpdateVisitor(Conversation):
    """Update a Crisp conversation's visitor details or subject; only the fields given change."""
    operation: Literal["update_visitor"] = operation("update_visitor", "Update Visitor Details", "Contacts")
    nickname: Optional[str] = Field(None, title="Name")
    email: Optional[str] = Field(None, title="Email")
    phone: Optional[str] = Field(None, title="Phone")
    subject: Optional[str] = Field(None, title="Subject")
    segments: Optional[List[str]] = Field(None, title="Segments", description="Replaces the conversation's segments (tags).")


class GetContact(BaseModel):
    """Get a contact's Crisp profile (name, company, segments, notes) by email or people_id."""
    operation: Literal["get_contact"] = operation("get_contact", "Get Contact", "Contacts")
    people_id: str = Field(..., min_length=1, pattern=r"^[^/?#\s]+$", title="Email or People ID",
                           description="The contact's email, or the people_id a conversation names.")


class GetWebsite(BaseModel):
    """Get the connected Crisp workspace: its name and domain."""
    operation: Literal["get_website"] = operation("get_website", "Get Workspace", "Workspace")


class OnVisitorMessage(BaseModel):
    """Wake when a visitor sends a message in a Crisp conversation. The team's replies and notes, and messages NoClick sent, never fire it."""
    operation: Literal["on_visitor_message"] = Field(TRIGGER_OPERATION, title="On Visitor Message", json_schema_extra={
        "const": TRIGGER_OPERATION, "ui:hidden": True, "x-display-name": "On Visitor Message",
        "x-category": "Triggers", "x-is-trigger": True,
    })
    subscription_status: Optional[str] = Field(
        None, title="Status", json_schema_extra={"ui:widget": "subscription_status", "ui:loadValue": True})
    trigger_registered: Optional[bool] = Field(None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    trigger_action: Optional[Dict[str, Any]] = Field(None, json_schema_extra={"ui:hidden": True})


CrispConfig = Annotated[Union[
    SendMessage, SendFile, AddNote, GetMessages,
    ListConversations, GetConversation, SetConversationState, AssignConversation, ListOperators,
    GetVisitor, UpdateVisitor, GetContact, GetWebsite, OnVisitorMessage,
], Discriminator("operation")]


class CrispNodeConfig(NodeConfig[CrispConfig, CrispAPITokenCredential]):
    pass


class CrispError(ValueError):
    """Crisp answered with an error: its HTTP status and its reason."""

    def __init__(self, status: int, reason: Any):
        super().__init__(f"Crisp HTTP {status}: {reason}")
        self.status = status


def _content_line(data: Dict[str, Any]) -> str:
    """What a visitor's message says, whatever its type."""
    content = data.get("content")
    if isinstance(content, str):
        return content
    content = content if isinstance(content, dict) else {}
    kind = data.get("type")
    if kind == "picker":
        chosen = [c.get("label") or c.get("value") for c in content.get("choices") or [] if c.get("selected")]
        return f"{content.get('text') or 'Picked'}: {', '.join(str(c) for c in chosen) or '(nothing)'}"
    if kind == "field":
        return f"{content.get('text') or 'Answered'}: {content.get('value') or '(empty)'}"
    if kind == "carousel":
        return str(content.get("text") or "[carousel]")
    return ""


def _attachments(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A message's files: a file/audio/animation message's own, and a text message's attachments."""
    content = data.get("content")
    if data.get("type") in ("file", "audio", "animation") and isinstance(content, dict) and content.get("url"):
        return [content]
    return [a for a in data.get("attachments") or [] if isinstance(a, dict) and a.get("url")]


class CrispNode(AppEventTriggerMixin, WorkflowNode):
    """Crisp live chat: reply to visitors, add notes, resolve and assign conversations, and wake on visitor messages."""

    integration_type = "automation-crisp"
    _app_provider = PROVIDER
    _trigger_event_map = {TRIGGER_OPERATION: [VISITOR_MESSAGE]}
    _credential_prompt = "Connect a Crisp API token to activate this trigger"
    # The teammates' names are this workspace's own; a workspace with none still has its name.
    connection_evidence = ConnectionEvidence(field="operator_id", noun="teammates", identity_operation="get_website",
                                             identity_keys=("name", "domain"))

    @classmethod
    def get_config_model(cls):
        return CrispNodeConfig

    @classmethod
    async def request(cls, identifier: str, key: str, tier: str, method: str, path: str, *,
                      params: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> Any:
        """One REST call; returns the envelope's ``data``. Raises ``CrispError``
        on a Crisp error, httpx errors as they come."""
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, API_BASE + path, auth=(identifier, key), params=params, json=body,
                                            headers={"X-Crisp-Tier": tier, "Accept": "application/json"})
        try:
            envelope = response.json()
        except ValueError:
            envelope = None
        if not 200 <= response.status_code < 300 or not isinstance(envelope, dict) or envelope.get("error"):
            raise CrispError(response.status_code,
                             envelope.get("reason") if isinstance(envelope, dict) else response.text[:200])
        return envelope.get("data")

    @classmethod
    async def call(cls, credential: Dict[str, Any], method: str, path: str, **kwargs) -> Any:
        token = CrispAPITokenCredential.model_validate(credential)
        return await cls.request(token.identifier, token.key, "website", method,
                                 f"/website/{token.website_id}{path}", **kwargs)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None):
        if field_name != "operator_id":
            return []
        operators = await cls.call(credential_data, "GET", "/operators/list")
        options = []
        for operator in operators or []:
            details = operator.get("details") or {}
            name = " ".join(p for p in (details.get("first_name"), details.get("last_name")) if p)
            if details.get("user_id"):
                options.append({"value": details["user_id"], "label": name or details.get("email") or details["user_id"]})
        return options

    # ── the trigger: NoClick's plugin hooks, fanned out by workspace ─────────

    @classmethod
    async def _resolve_tenant_id(cls, credential: Dict[str, Any]) -> Optional[str]:
        """The workspace the token reaches; reading it proves the token does."""
        website_id = CrispAPITokenCredential.model_validate(credential).website_id
        try:
            await cls.call(credential, "GET", "")
        except httpx.HTTPError as e:
            raise RegistrationUnverified(f"Crisp didn't answer: {e}") from e
        except CrispError as e:
            if e.status in (401, 403, 404):
                raise ValueError(f"Crisp refused this API token for website {website_id} ({e})") from e
            raise RegistrationUnverified(str(e)) from e
        return website_id

    @classmethod
    def _subscription_status_line(cls, event_types, config):
        return "Active — listening for visitor messages"

    @classmethod
    async def check_registration_health(cls, credential, operation, config) -> Optional[RegistrationAdvisory]:
        """Crisp sends a workspace's chats to NoClick only through NoClick's
        plugin, so a trigger is deaf until the workspace installed it."""
        if not os.environ.get(HOOK_SECRET_ENV, "").strip():
            return RegistrationAdvisory("Crisp can't send chats to this NoClick server: its Crisp plugin isn't set up")
        plugin_id = os.environ.get(PLUGIN_ID_ENV, "").strip()
        identifier = os.environ.get(PLUGIN_IDENTIFIER_ENV, "").strip()
        key = os.environ.get(PLUGIN_KEY_ENV, "").strip()
        if not (plugin_id and identifier and key):
            return None
        website_id = CrispAPITokenCredential.model_validate(credential).website_id
        try:
            await cls.request(identifier, key, "plugin", "GET", f"/plugins/subscription/{website_id}/{plugin_id}")
        except CrispError as e:
            if e.status != 404:
                raise
            where = os.environ.get(PLUGIN_INSTALL_URL_ENV, "").strip() or "in Crisp, Settings → Plugins"
            return RegistrationAdvisory(f"Add the NoClick plugin to this Crisp workspace so its chats reach NoClick: {where}")
        return None

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A visitor's message → the agent's turn, the conversation's session_id
        as its key (one thread per Crisp conversation) and named in the text for
        the reply tools. A file reads as what it is, and the agent gets it."""
        data = output.get("data") if isinstance(output, dict) else None
        if not isinstance(data, dict) or output.get("event") != VISITOR_MESSAGE or not data.get("session_id"):
            return super().resolve_agent_event(output)
        from nodes.core.agent_events import media_entry
        from nodes.core.media_digest import media_kind, media_placeholder

        session_id = data["session_id"]
        visitor = (data.get("user") or {}).get("nickname") or "a visitor"
        text = _content_line(data)
        entries, notes = [], []
        for item in _attachments(data):
            kind = media_kind(item.get("type"), item.get("name"))
            voice = data.get("type") == "audio"
            text = text or media_placeholder(kind, voice=voice, filename=item.get("name"))
            notes.append(f"Attached {item.get('name') or kind} ({item.get('type') or 'unknown type'}): {item['url']}")
            entries.append(media_entry(url=item["url"], mime_type=item.get("type"), filename=item.get("name"),
                                       duration_s=item.get("duration"), voice=voice, record=item))
        via = "" if data.get("origin") in (None, "chat") else f" via {data['origin']}"
        lines = [f"Crisp message from {visitor}{via} in conversation {session_id}:", text or "[empty message]", *notes,
                 "", f"To reply, call send_message with session_id={session_id}."]
        return {"text": "\n".join(lines), "conversation_key": session_id, "title": f"Crisp: {visitor}", "media": entries}

    # ── operations ─────────────────────────────────────────────────────────

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, CrispNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Crisp API token in the credentials tab")
        config, credential = self.config.config, self.config.credentials.model_dump()
        op = config.operation
        if op == TRIGGER_OPERATION:
            return self.no_event_output(op, "It fires when a visitor writes in a Crisp conversation.")
        started = time.monotonic()
        conversation = f"/conversation/{config.session_id}" if hasattr(config, "session_id") else ""
        if op in ("send_message", "send_file", "add_note"):
            data = await self._send(credential, config, conversation)
        elif op == "get_messages":
            params = {"timestamp_before": config.before_timestamp} if config.before_timestamp else None
            data = {"messages": await self.call(credential, "GET", f"{conversation}/messages", params=params)}
        elif op == "list_conversations":
            data = {"conversations": await self.call(
                credential, "GET", f"/conversations/{config.page}", params=self._list_params(config)), "page": config.page}
        elif op == "get_conversation":
            data = await self.call(credential, "GET", conversation)
        elif op == "set_conversation_state":
            data = await self.call(credential, "PATCH", f"{conversation}/state", body={"state": config.state})
        elif op == "assign_conversation":
            data = await self.call(credential, "PATCH", f"{conversation}/routing",
                                   body={"assigned": {"user_id": config.operator_id}})
        elif op == "list_operators":
            data = {"operators": await self.call(credential, "GET", "/operators/list")}
        elif op == "get_visitor":
            data = await self.call(credential, "GET", f"{conversation}/meta")
        elif op == "update_visitor":
            meta = config.model_dump(include={"nickname", "email", "phone", "subject", "segments"}, exclude_none=True)
            if not meta:
                raise ValueError("Give at least one visitor detail to update")
            data = await self.call(credential, "PATCH", f"{conversation}/meta", body=meta)
        elif op == "get_contact":
            data = await self.call(credential, "GET", f"/people/profile/{quote(config.people_id, safe='@')}")
        else:  # get_website
            data = await self.call(credential, "GET", "")
        return {"status": "success", "operation": op, "data": data,
                "timing_ms": {"request": round((time.monotonic() - started) * 1000, 2)}}

    async def _send(self, credential: Dict[str, Any], config, conversation: str) -> Any:
        """Messages go out as the operator, so Crisp delivers them as
        ``message:received`` and no visitor-message trigger hears them; their
        fingerprint is recorded too, for any trigger that would."""
        if config.operation == "send_file":
            body = {"type": "file", "content": {"name": config.file_name, "url": config.file_url, "type": config.mime_type}}
        else:
            body = {"type": "note" if config.operation == "add_note" else "text",
                    "content": config.note if config.operation == "add_note" else config.message}
        body.update({"from": "operator", "origin": "chat"})
        if getattr(config, "sender_name", None):
            body["user"] = {"type": "participant", "nickname": config.sender_name}
        data = await self.call(credential, "POST", f"{conversation}/message", body=body)
        fingerprint = (data or {}).get("fingerprint") if isinstance(data, dict) else None
        await record_self_post(PROVIDER, sent_message_key(config.session_id, fingerprint))
        return data

    @staticmethod
    def _list_params(config: ListConversations) -> Dict[str, Any]:
        params: Dict[str, Any] = {"per_page": config.per_page}
        if config.search:
            params.update(search_query=config.search, search_type="text")
        if config.status == "resolved":
            params["filter_resolved"] = 1
        elif config.status == "unresolved":
            params["filter_not_resolved"] = 1
        if config.unread_only == "true":
            params["filter_unread"] = 1
        if config.unassigned_only == "true":
            params["filter_unassigned"] = 1
        return params
