"""Email over IMAP and SMTP: Yahoo Mail, AOL, iCloud, Zoho Mail, Fastmail, GMX,
mail.com and company mailboxes, connected with an address and an app password.

Reads, flags and files messages over IMAP and sends from the mailbox itself
over SMTP, so no NoClick mail domain is involved in what it sends. A message is
named by its folder and UID (with the folder's UIDVALIDITY, which a rebuilt
folder changes). Nothing is ever deleted: moving to Trash is the way to throw
mail away. The protocol work lives in ``nodes/imap_mailbox.py``.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes import imap_mailbox as mailbox
from nodes.imap_mailbox import MailError

logger = logging.getLogger(__name__)

# The newest messages a trigger tick looks at, and how many of the new ones it
# hands on; the rest wait for the next tick, oldest first.
TRIGGER_WINDOW_UIDS = 2000
TRIGGER_MAX_PER_POLL = 10
# Search widens its UID window this way until it has enough matches.
SEARCH_WINDOWS = (5000, 50000)
MAX_UIDS_PER_CALL = 500
MAX_RECIPIENTS = 100

INSTRUCTIONS = (
    "Sign in with your email address and an app password, a password your provider makes for one app: most no "
    "longer let apps use your normal password.\n"
    "- Yahoo Mail: https://login.yahoo.com/account/security (Generate app password)\n"
    "- AOL: https://login.aol.com/account/security (Generate app password)\n"
    "- iCloud Mail: https://account.apple.com (Sign-In and Security, then App-Specific Passwords)\n"
    "- Zoho Mail: https://accounts.zoho.com/home#security/app_password (and turn on IMAP access in Zoho Mail's "
    "settings)\n"
    "- Fastmail: https://app.fastmail.com/settings/security (Manage app passwords)\n"
    "- GMX and mail.com: turn on POP3 & IMAP access in the mailbox's settings (mail.com has it with Premium).\n"
    "For these, NoClick knows the servers. For a company or any other mailbox, open More options and enter the "
    "IMAP and SMTP servers your provider gives. Gmail and Outlook.com don't take an app password here: use "
    "NoClick's Gmail or Outlook step, which signs in with Google or Microsoft."
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
# Yahoo and AOL show an app password as four groups of four letters; the spaces aren't part of it.
_GROUPED_APP_PASSWORD = re.compile(r"^[A-Za-z]{4}(?: [A-Za-z]{4}){3}$")
_SECURITY = {"enum": ["auto", "ssl", "starttls"],
             "enumNames": ["Automatic (from the port)", "SSL/TLS", "STARTTLS"]}
_OPTIONAL_KEYS = ("username", "imap_host", "imap_port", "imap_security", "smtp_host", "smtp_port", "smtp_security")


def _host(value: Optional[str], kind: str) -> Tuple[Optional[str], Optional[int]]:
    """A server name out of what was pasted: ``imaps://imap.example.com:993/`` reads ``imap.example.com``, 993."""
    raw = (value or "").strip()
    if not raw:
        return None, None
    raw = re.sub(r"^[a-z][a-z0-9+.-]*://", "", raw, flags=re.I).split("/", 1)[0]
    port = None
    match = re.match(r"^(.*?):(\d{1,5})$", raw)
    if match and not raw.startswith("["):
        raw, port = match.group(1), int(match.group(2))
    host = raw.strip("[]").lower().rstrip(".")
    if not _HOST_RE.match(host):
        try:
            import ipaddress

            ipaddress.ip_address(host)
        except ValueError:
            raise ValueError(f"{kind} server should be a host name, like imap.example.com.") from None
    if not mailbox.is_public_host(host):
        raise ValueError(f"{kind} server {host} is on a private network, which NoClick can't reach.")
    return host, port


class ImapCredential(BaseModel):
    """An email account over IMAP and SMTP, signed in with an app password."""

    model_config = ConfigDict(
        title="App Password",
        hide_input_in_errors=True,
        json_schema_extra={"x-credential-instructions": INSTRUCTIONS},
    )

    credential_type: Literal["imap_smtp"] = Field("imap_smtp", json_schema_extra={"ui:hidden": True})
    # The servers come before the address: the address's check reads them.
    imap_host: Optional[str] = Field(
        None, title="IMAP server",
        description="Filled in for Yahoo, AOL, iCloud, Zoho, Fastmail, GMX and mail.com addresses.",
        json_schema_extra={"ui:placeholder": "imap.example.com"},
    )
    imap_port: Optional[int] = Field(None, title="IMAP port", json_schema_extra={"ui:placeholder": "993"})
    imap_security: Literal["auto", "ssl", "starttls"] = Field("auto", title="IMAP security",
                                                              json_schema_extra=_SECURITY)
    smtp_host: Optional[str] = Field(
        None, title="SMTP server",
        description="Filled in for Yahoo, AOL, iCloud, Zoho, Fastmail, GMX and mail.com addresses.",
        json_schema_extra={"ui:placeholder": "smtp.example.com"},
    )
    smtp_port: Optional[int] = Field(None, title="SMTP port", json_schema_extra={"ui:placeholder": "465"})
    smtp_security: Literal["auto", "ssl", "starttls"] = Field("auto", title="SMTP security",
                                                              json_schema_extra=_SECURITY)
    email: str = Field(..., title="Email address", json_schema_extra={"ui:placeholder": "you@yahoo.com"})
    password: str = Field(
        ..., title="App password", repr=False,
        description="The app password your provider made for NoClick, not your normal password.",
        json_schema_extra={"ui:widget": "password"},
    )
    username: Optional[str] = Field(
        None, title="Username",
        description="Only if your server signs in with something other than your email address.",
    )

    @model_validator(mode="before")
    @classmethod
    def _servers_from_address(cls, data: Any) -> Any:
        """Blank optional fields are unset, a port written on a host (``mail.example.com:587``) fills an empty
        port, and a known provider's servers are filled in from the address."""
        if not isinstance(data, dict):
            return data
        data = {k: v for k, v in data.items() if not (k in _OPTIONAL_KEYS and v in (None, ""))}
        for kind in ("imap", "smtp"):
            raw = data.get(f"{kind}_host")
            match = re.search(r":(\d{1,5})/?$", raw.strip()) if isinstance(raw, str) else None
            if match and f"{kind}_port" not in data:
                data[f"{kind}_port"] = int(match.group(1))
        preset = mailbox.preset_for(str(data.get("email") or "").strip())
        if preset:
            for kind, host, port in (("imap", preset.imap_host, 993), ("smtp", preset.smtp_host, preset.smtp_port)):
                if not data.get(f"{kind}_host"):
                    data[f"{kind}_host"] = host
                    data.setdefault(f"{kind}_port", port)
        return data

    @field_validator("imap_host")
    @classmethod
    def _imap_host(cls, value: Optional[str]) -> Optional[str]:
        return _host(value, "IMAP")[0]

    @field_validator("smtp_host")
    @classmethod
    def _smtp_host(cls, value: Optional[str]) -> Optional[str]:
        return _host(value, "SMTP")[0]

    @field_validator("imap_port")
    @classmethod
    def _imap_port(cls, value: Optional[int]) -> Optional[int]:
        if value is not None:
            mailbox.check_port(value, "IMAP")
        return value

    @field_validator("smtp_port")
    @classmethod
    def _smtp_port(cls, value: Optional[int]) -> Optional[int]:
        if value is not None:
            mailbox.check_port(value, "SMTP")
        return value

    @field_validator("email")
    @classmethod
    def _address(cls, value: str, info) -> str:
        address = value.strip()
        local, _, domain = address.rpartition("@")
        address = f"{local}@{domain.lower()}"
        if not _EMAIL_RE.match(address):
            raise ValueError("Email address should look like you@example.com.")
        missing = [kind for kind in ("IMAP", "SMTP") if not info.data.get(f"{kind.lower()}_host")]
        if missing:
            elsewhere = mailbox.SIGN_IN_ELSEWHERE.get(mailbox.domain_of(address))
            if elsewhere and len(missing) == 2:
                raise ValueError(f"{elsewhere} doesn't take an app password here. Connect it with NoClick's "
                                 f"{elsewhere} step, which signs in with "
                                 f"{'Google' if elsewhere == 'Gmail' else 'Microsoft'}.")
            if len(missing) == 2:
                raise ValueError(f"NoClick doesn't know {mailbox.domain_of(address)}'s mail servers. Under More "
                                 "options, enter the IMAP and SMTP servers your provider gives.")
            raise ValueError(f"Under More options, enter the {missing[0]} server too.")
        return address

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return value.replace(" ", "") if _GROUPED_APP_PASSWORD.match(value.strip()) else value

    @field_validator("username")
    @classmethod
    def _username(cls, value: Optional[str]) -> Optional[str]:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def _ports_and_security(self) -> "ImapCredential":
        for kind, ports in (("imap", mailbox.IMAP_PORTS), ("smtp", mailbox.SMTP_PORTS)):
            label = kind.upper()
            port = getattr(self, f"{kind}_port")
            security = getattr(self, f"{kind}_security")
            if port is None:
                port = next(p for p, s in ports.items() if s == ("starttls" if security == "starttls" else "ssl"))
                setattr(self, f"{kind}_port", port)
            if security == "auto":
                setattr(self, f"{kind}_security", mailbox.default_security(port, label))
        return self

    def logins(self) -> Tuple[str, str]:
        """``(IMAP login, SMTP login)``: the username when set, else the address (or, where a provider signs
        in to IMAP with the name before the @, that)."""
        if self.username:
            return self.username, self.username
        local_part = self.imap_host in mailbox.LOCAL_PART_LOGIN_HOSTS
        return (self.email.rpartition("@")[0] if local_part else self.email), self.email

    async def account(self) -> mailbox.Account:
        imap_login, smtp_login = self.logins()
        return await mailbox.resolve_account(
            email_address=self.email, password=self.password,
            imap=(self.imap_host, self.imap_port, self.imap_security, imap_login),
            smtp=(self.smtp_host, self.smtp_port, self.smtp_security, smtp_login),
        )


# ---------------------------------------------------------------- configs

_FOLDER_OPTIONS = {"field_name": "folder", "placeholder": "Select a folder...", "searchable": True,
                   "allow_custom": True, "custom_placeholder": "Or type a folder name"}


def _operation(name: str, label: str, category: str, description: str, keywords: Tuple[str, ...] = (),
               trigger: bool = False):
    return Field(name, title=label, description=description, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category, "x-is-trigger": trigger,
        "x-display-name": label, **({"x-keywords": list(keywords)} if keywords else {}),
    })


def _folder(title: str = "Folder", default: Optional[str] = "INBOX", description: str = "The folder to look in."):
    return Field(default, title=title, description=description,
                 json_schema_extra={"x-dynamic-options": _FOLDER_OPTIONS})


def _uids(value: Any, *, single: bool) -> str:
    """UIDs as IMAP writes them; an upstream number arrives as an int."""
    if isinstance(value, bool):
        raise ValueError("UID must be a number.")
    if isinstance(value, (list, tuple)):
        value = ",".join(str(v) for v in value)
    text = re.sub(r"\s+", "", str(value if value is not None else ""))
    parts = [p for p in text.split(",") if p]
    if not parts or not all(p.isdigit() and int(p) > 0 for p in parts):
        raise ValueError("UID must be a message's number in its folder, like 1234" +
                         ("." if single else ", or several: 1234,1235."))
    if single and len(parts) > 1:
        raise ValueError("Name one message's UID here.")
    if len(parts) > MAX_UIDS_PER_CALL:
        raise ValueError(f"At most {MAX_UIDS_PER_CALL} messages at a time.")
    return ",".join(str(int(p)) for p in dict.fromkeys(parts))


class _Message(BaseModel):
    folder: str = _folder(description="The folder the message is in.")
    uid: str = Field(..., title="Message UID",
                     description="The message's UID in its folder, from Search messages or the New email trigger.")
    uidvalidity: Optional[int] = Field(
        None, title="UIDVALIDITY",
        description="The folder's UIDVALIDITY that came with the UID. With it, a folder rebuilt since then is "
                    "refused instead of acting on another message.",
        json_schema_extra={"ui:category": "Options"},
    )

    @field_validator("uid", mode="before")
    @classmethod
    def _one_uid(cls, value: Any) -> str:
        return _uids(value, single=True)


class _Messages(_Message):
    uid: str = Field(..., title="Message UIDs",
                     description="One message's UID, or several separated by commas (1234,1235).")

    @field_validator("uid", mode="before")
    @classmethod
    def _one_uid(cls, value: Any) -> str:
        return _uids(value, single=False)


class _Filters(BaseModel):
    unread_only: bool = Field(False, title="Unread only")
    sender: Optional[str] = Field(None, title="From", description="Messages whose sender contains this: an "
                                  "address, a domain or a name.")
    recipient: Optional[str] = Field(None, title="To", description="Messages whose To contains this.")
    subject: Optional[str] = Field(None, title="Subject contains")
    text: Optional[str] = Field(None, title="Text contains",
                                description="Anywhere in the message: its headers, body and attachments' names.")

    def criteria(self) -> List[Tuple[str, Optional[str]]]:
        out: List[Tuple[str, Optional[str]]] = []
        if self.unread_only:
            out.append(("UNSEEN", None))
        for keyword, value in (("FROM", self.sender), ("TO", self.recipient), ("SUBJECT", self.subject),
                               ("TEXT", self.text)):
            if value and value.strip():
                out.append((keyword, value.strip()))
        return out


class _Compose(BaseModel):
    text: Optional[str] = Field(None, title="Text", description="The message as plain text.",
                                json_schema_extra={"ui:widget": "textarea"})
    html: Optional[str] = Field(None, title="HTML", description="The message as HTML. Without Text, its text is "
                                "made from this.", json_schema_extra={"ui:widget": "textarea"})
    cc: List[str] = Field(default_factory=list, title="Cc", json_schema_extra={"ui:widget": "list"})
    bcc: List[str] = Field(default_factory=list, title="Bcc", json_schema_extra={"ui:widget": "list"})
    attachments: List[str] = Field(
        default_factory=list, title="Attachments",
        description="Files to attach: workflow resource ids or URLs (max 10MB per file, 20MB total).",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )
    from_name: Optional[str] = Field(None, title="From name", description="The name shown beside your address.",
                                     json_schema_extra={"ui:category": "Options"})
    save_to_sent: bool = Field(
        False, title="File a copy in Sent",
        description="Most providers keep no copy of mail sent over SMTP. Turn this on to file one in your Sent "
                    "folder.", json_schema_extra={"ui:category": "Options"})

    @field_validator("cc", "bcc", "attachments", mode="before")
    @classmethod
    def _list(cls, value: Any) -> List[str]:
        return _string_list(value)

    @model_validator(mode="after")
    def _has_body(self):
        if not ((self.text or "").strip() or (self.html or "").strip()):
            raise ValueError("Write the message: Text, HTML or both.")
        return self


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


class ImapListFoldersConfig(BaseModel):
    operation: Literal["list_folders"] = _operation(
        "list_folders", "List folders", "Mailbox", "The mailbox's folders, with which one is Sent, Trash and so on.",
        ("mailboxes", "labels", "folders"))


class ImapCheckConnectionConfig(BaseModel):
    operation: Literal["check_connection"] = _operation(
        "check_connection", "Check connection", "Mailbox",
        "Sign in to the IMAP and SMTP servers, sending nothing, and show the newest senders in the inbox.",
        ("test login", "verify account"))


class ImapSearchMessagesConfig(_Filters):
    operation: Literal["search_messages"] = _operation(
        "search_messages", "Search messages", "Messages",
        "Find messages in a folder, newest first, with their headers and the start of each.",
        ("find email", "read inbox", "list emails", "unread mail", "get emails"))
    folder: str = _folder()
    since: Optional[str] = Field(None, title="Since", description="Messages that arrived on or after this day, "
                                 "e.g. 2026-11-01.")
    limit: int = Field(20, title="Limit", ge=1, le=100, description="How many messages, newest first (1-100).")
    include_snippet: bool = Field(True, title="Include the start of each message",
                                  json_schema_extra={"ui:category": "Options"})

    @field_validator("since")
    @classmethod
    def _since(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        try:
            return date.fromisoformat(str(value).strip()[:10]).isoformat()
        except ValueError:
            raise ValueError("Since should be a day like 2026-11-01.") from None


class ImapGetMessageConfig(_Message):
    operation: Literal["get_message"] = _operation(
        "get_message", "Get a message", "Messages",
        "One message whole: its headers, text, HTML and attachments (kept as files). Reading it doesn't mark it "
        "read.", ("read email", "open email", "email body", "download attachment"))
    download_attachments: bool = Field(True, title="Keep attachments as files",
                                       json_schema_extra={"ui:category": "Options"})


class ImapMarkAsReadConfig(_Messages):
    operation: Literal["mark_as_read"] = _operation(
        "mark_as_read", "Mark as read", "Messages", "Mark messages read.", ("mark seen",))


class ImapMarkAsUnreadConfig(_Messages):
    operation: Literal["mark_as_unread"] = _operation(
        "mark_as_unread", "Mark as unread", "Messages", "Mark messages unread.", ("mark unseen",))


class ImapMoveMessageConfig(_Messages):
    operation: Literal["move_message"] = _operation(
        "move_message", "Move a message", "Messages",
        "Move messages to another folder: Archive, Trash or one of yours. Nothing is ever deleted for good.",
        ("archive email", "delete email", "trash email", "file email"))
    destination_folder: str = Field(..., title="Move to", json_schema_extra={"x-dynamic-options": _FOLDER_OPTIONS})


class ImapSendEmailConfig(_Compose):
    operation: Literal["send_email"] = _operation(
        "send_email", "Send an email", "Send", "Send an email from this mailbox over its SMTP server.",
        ("compose email", "email someone", "send mail", "write email"))
    to: List[str] = Field(..., title="To", description="Addresses, or names with addresses: Ana <ana@example.com>.",
                          json_schema_extra={"ui:widget": "list"})
    subject: str = Field(..., title="Subject")

    @field_validator("to", mode="before")
    @classmethod
    def _to(cls, value: Any) -> List[str]:
        return _string_list(value)


class ImapReplyToMessageConfig(_Message, _Compose):
    operation: Literal["reply_to_message"] = _operation(
        "reply_to_message", "Reply to a message", "Send",
        "Reply to a message from this mailbox, in its thread: to its sender, or with Reply all to everyone on it.",
        ("respond to email", "answer email", "reply all"))
    reply_all: bool = Field(False, title="Reply all")


class ImapOnNewEmailConfig(_Filters, PollTriggerConfigBase):
    operation: Literal["on_new_email"] = _operation(
        "on_new_email", "New email", "Triggers", "Runs for each new message in a folder that matches the filters.",
        ("email received", "incoming email", "watch inbox"), trigger=True)
    folder: str = _folder(description="The folder to watch.")
    download_attachments: bool = Field(True, title="Keep attachments as files",
                                       json_schema_extra={"ui:category": "Options"})


ImapConfig = Annotated[
    Union[
        ImapSearchMessagesConfig, ImapGetMessageConfig, ImapSendEmailConfig, ImapReplyToMessageConfig,
        ImapMarkAsReadConfig, ImapMarkAsUnreadConfig, ImapMoveMessageConfig, ImapListFoldersConfig,
        ImapCheckConnectionConfig, ImapOnNewEmailConfig,
    ],
    Discriminator("operation"),
]


class ImapNodeConfig(NodeConfig[ImapConfig, ImapCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# ------------------------------------------------------------------- node


def _recipients(entries: List[str], field: str) -> List[str]:
    out: List[str] = []
    for entry in entries:
        found = mailbox.addresses(entry)
        if not found or not all(_EMAIL_RE.match(a) for a in found):
            raise ValueError(f"{field}: {entry!r} isn't an email address.")
        out += found
    return out


def _message_out(folder: str, uidvalidity: int, uid: int, fetched: Dict[str, Any]) -> Dict[str, Any]:
    flags = fetched.get("flags") or []
    return {"folder": folder, "uid": uid, "uidvalidity": uidvalidity,
            "unread": not any(f.lower() == "\\seen" for f in flags), "flags": flags,
            "size": fetched.get("size"), "received_at": fetched.get("internal_date")}


class ImapNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-imap"
    credential_provider_labels = {"imap": "Email Account"}
    connection_evidence = ConnectionEvidence(
        operation="check_connection",
        noun="recent senders",
        label_keys=("from",),
        identity_operation="check_connection",
        identity_keys=("email",),
    )
    edit_examples = [
        "Search my Yahoo inbox for unread invoices",
        "Reply to the newest email from a customer",
        "Move newsletters to Archive",
        "Run an agent on every new email in iCloud",
    ]

    @classmethod
    def get_config_model(cls):
        return ImapNodeConfig

    @classmethod
    def should_propagate_output(cls, output: Dict[str, Any], config: Dict[str, Any]) -> bool:
        if config.get("operation") == "on_new_email":
            return bool(output.get("new_message_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """New mail → what a person would read: sender, subject and the start of each (five at most), each
        attachment as media the agent digests. One message keys the conversation on its thread, so a reply in
        that thread comes back to the same conversation; a batch keys nothing."""
        from nodes.core.agent_events import media_entry, prune_empty

        messages = output.get("messages") if isinstance(output, dict) else None
        if not isinstance(messages, list):
            return super().resolve_agent_event(output)
        messages = [m for m in messages if isinstance(m, dict)]
        if not messages:
            return None
        one = messages[0] if len(messages) == 1 else None
        clip = 1500 if one else 400
        account = output.get("account")
        where = f"{account}, {output.get('folder') or 'INBOX'}" if account else output.get("folder") or "INBOX"
        lines = [f"New email in {where}" if one else f"{len(messages)} new emails in {where}"]
        media = []
        for m in messages[:5]:
            lines += ["", f"From: {m.get('from') or '(unknown sender)'}"]
            if m.get("date"):
                lines.append(f"Date: {m['date']}")
            lines.append(f"Subject: {m.get('subject') or '(no subject)'}")
            lines.append(f"Folder: {m.get('folder')}, UID {m.get('uid')}")
            body = m.get("text") or m.get("snippet") or "(empty body)"
            lines += ["", prune_empty(str(body), max_str=clip)]
            for a in m.get("attachments") or []:
                if not isinstance(a, dict):
                    continue
                lines.append(f"Attachment: {a.get('filename')} ({a.get('mime_type')}, {a.get('size_bytes')} bytes)"
                             + (f": {a['url']}" if a.get("url") else ""))
                if a.get("url"):
                    media.append(media_entry(url=a["url"], mime_type=a.get("mime_type"), filename=a.get("filename"),
                                             size_bytes=a.get("size_bytes"), resource_id=a.get("resource_id"),
                                             record=a))
            if m.get("attachments_note"):
                lines.append(m["attachments_note"])
        if len(messages) > 5:
            rest = "; ".join(str(m.get("subject") or "(no subject)") for m in messages[5:])
            lines += ["", f"…and {len(messages) - 5} more: {prune_empty(rest, max_str=300)}"]
        target = (f"folder {one.get('folder')!r} and uid {one.get('uid')}" if one
                  else "the folder and UID shown above")
        return {
            "text": prune_empty("\n".join(lines), max_str=6000)
                    + f"\n\nTo reply in the thread, call reply_to_message with {target}.",
            "conversation_key": (one.get("thread") if one else None),
            "title": (one.get("subject") or "New email") if one else f"{len(messages)} new emails",
            "media": media,
        }

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Dict[str, Any],
                                 context: Optional[Dict[str, Any]] = None, page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> Dict[str, Any]:
        if field_name != "folder":
            return {"options": []}
        if not credential_data:
            raise ValueError("Connect an email account to list its folders")
        account = await ImapCredential.model_validate(credential_data).account()
        folders = await mailbox.run_on_mailbox(
            lambda c: _with_imap(account, c, lambda imap: imap.folders()), deadline_s=45, what="listing folders")
        needle = (search or "").strip().lower()
        return {"options": [{"value": f["name"], "label": f["name"]} for f in folders
                            if f["selectable"] and needle in f["name"].lower()]}

    # ---- execute

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, ImapNodeConfig):
            raise ValueError("Email (IMAP/SMTP) configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an email account: its address and an app password.")
        op = self.config.config
        account = await credential.account()
        handler = {
            "list_folders": self._list_folders,
            "check_connection": self._check_connection,
            "search_messages": self._search_messages,
            "get_message": self._get_message,
            "mark_as_read": self._mark,
            "mark_as_unread": self._mark,
            "move_message": self._move,
            "send_email": self._send,
            "reply_to_message": self._send,
            "on_new_email": self._poll,
        }[op.operation]
        return await handler(op, account)

    async def _list_folders(self, op, account) -> Dict[str, Any]:
        folders = await mailbox.run_on_mailbox(
            lambda c: _with_imap(account, c, lambda imap: imap.folders()), deadline_s=45, what="listing folders")
        return {"folders": folders, "count": len(folders)}

    async def _check_connection(self, op, account) -> Dict[str, Any]:
        def work(connections):
            with mailbox.Imap(account, connections) as imap:
                state = imap.open("INBOX")
                newest = imap.search([(f"UID {max(1, (state.uidnext or 1) - 200)}:*", None)])[-8:]
                headers = imap.fetch(newest, f"(UID BODY.PEEK[HEADER.FIELDS ({mailbox.HEADER_FIELDS})])")
            mailbox.check_smtp(account, connections)
            rows = []
            for uid in sorted(headers, reverse=True):
                h = mailbox.headers_of(mailbox.parse(headers[uid].get("header") or b""))
                rows.append({"from": h["from"], "subject": h["subject"], "date": h["date"]})
            return state, rows

        state, rows = await mailbox.run_on_mailbox(work, deadline_s=45, what="checking the connection")
        return {
            "email": account.email,
            "imap": {"host": account.imap.host, "port": account.imap.port, "security": account.imap.security},
            "smtp": {"host": account.smtp.host, "port": account.smtp.port, "security": account.smtp.security},
            "inbox_messages": state.exists,
            "recent_messages": rows,
        }

    async def _search_messages(self, op: ImapSearchMessagesConfig, account) -> Dict[str, Any]:
        criteria = op.criteria()
        if op.since:
            criteria.append((f"SINCE {mailbox.imap_date(date.fromisoformat(op.since))}", None))
        items = "(UID FLAGS RFC822.SIZE INTERNALDATE BODY.PEEK[HEADER.FIELDS (" + mailbox.HEADER_FIELDS + ")]" + (
            f" BODY.PEEK[]<0.{mailbox.SNIPPET_READ_BYTES}>" if op.include_snippet else "") + ")"

        def work(connections):
            with mailbox.Imap(account, connections) as imap:
                state = imap.open(op.folder)
                uids = _newest_matches(imap, state, criteria, op.limit)
                found = imap.fetch(uids[-op.limit:], items)
            return state, uids, found

        state, uids, found = await mailbox.run_on_mailbox(work, deadline_s=90, what="searching")
        messages = []
        for uid in sorted(found, reverse=True):
            fetched = found[uid]
            row = {**_message_out(op.folder, state.uidvalidity, uid, fetched),
                   **mailbox.headers_of(mailbox.parse(fetched.get("header") or b""))}
            if op.include_snippet:
                row["snippet"] = mailbox.snippet(mailbox.parse(fetched.get("body") or b""))
            row["thread"] = mailbox.thread_key(row)
            messages.append(row)
        return {"folder": op.folder, "uidvalidity": state.uidvalidity, "messages": messages,
                "count": len(messages), "total_matches": len(uids)}

    async def _get_message(self, op: ImapGetMessageConfig, account) -> Dict[str, Any]:
        uid = int(op.uid)

        def work(connections):
            with mailbox.Imap(account, connections) as imap:
                state = _opened(imap, op)
                return state, _read_whole(imap, [uid])

        state, raw = await mailbox.run_on_mailbox(work, deadline_s=120, what="reading the message")
        if uid not in raw:
            raise MailError(f"There's no message with UID {uid} in {op.folder!r}. Search the folder for its UID.")
        return await self._message(op.folder, state.uidvalidity, uid, raw[uid], keep=op.download_attachments)

    async def _mark(self, op: _Messages, account) -> Dict[str, Any]:
        read = op.operation == "mark_as_read"
        uids = [int(u) for u in op.uid.split(",")]

        def work(connections):
            with mailbox.Imap(account, connections) as imap:
                _opened(imap, op, write=True)
                _require(imap, op.folder, uids)
                imap.flag_seen(uids, read)

        await mailbox.run_on_mailbox(work, deadline_s=60, what="marking the messages")
        return {"status": "success", "folder": op.folder, "uids": uids, "read": read}

    async def _move(self, op: ImapMoveMessageConfig, account) -> Dict[str, Any]:
        uids = [int(u) for u in op.uid.split(",")]
        if op.destination_folder == op.folder:
            raise ValueError("The message is already in that folder.")

        def work(connections):
            with mailbox.Imap(account, connections) as imap:
                _opened(imap, op, write=True)
                _require(imap, op.folder, uids)
                imap.move(uids, op.destination_folder)

        await mailbox.run_on_mailbox(work, deadline_s=60, what="moving the messages")
        return {"status": "success", "folder": op.folder, "destination_folder": op.destination_folder, "uids": uids}

    async def _send(self, op: Union[ImapSendEmailConfig, ImapReplyToMessageConfig], account) -> Dict[str, Any]:
        from nodes.core.media_resolver import resolve_attachments

        replying = isinstance(op, ImapReplyToMessageConfig)
        original: Dict[str, Any] = {}
        if replying:
            uid = int(op.uid)

            def read(connections):
                with mailbox.Imap(account, connections) as imap:
                    _opened(imap, op)
                    return imap.fetch([uid], f"(UID BODY.PEEK[HEADER.FIELDS ({mailbox.HEADER_FIELDS})])")

            found = await mailbox.run_on_mailbox(read, deadline_s=45, what="reading the message to reply to")
            if uid not in found:
                raise MailError(f"There's no message with UID {uid} in {op.folder!r} to reply to.")
            original = mailbox.headers_of(mailbox.parse(found[uid].get("header") or b""))
            to, cc = _reply_recipients(original, account.email, op.reply_all)
            if not to:
                raise MailError("The message names no sender to reply to.")
            subject = original.get("subject") or ""
            subject = subject if re.match(r"^\s*re\s*:", subject, re.I) else f"Re: {subject}".rstrip()
            cc += [c for c in _recipients(op.cc, "Cc") if c.lower() not in {a.lower() for a in to + cc}]
        else:
            to, cc, subject = _recipients(op.to, "To"), _recipients(op.cc, "Cc"), op.subject
            if not to:
                raise ValueError("To: name at least one recipient.")
        bcc = _recipients(op.bcc, "Bcc")
        everyone = list(dict.fromkeys(a.lower() for a in to + cc + bcc))
        if len(everyone) > MAX_RECIPIENTS:
            raise ValueError(f"At most {MAX_RECIPIENTS} recipients per message.")

        text = await self._brand_email_body(op.text, html=False) if (op.text or "").strip() else None
        html = await self._brand_email_body(op.html, html=True) if (op.html or "").strip() else None
        files = [(m.filename, m.mime_type, m.data)
                 for m in await resolve_attachments(op.attachments, workflow_id=self.workflow_id)]
        references = original.get("references", [])[-19:] + ([original["message_id"]]
                                                               if original.get("message_id") else [])
        try:
            message = mailbox.compose(
                sender=account.email, from_name=op.from_name, to=to, cc=cc, subject=subject, text=text, html=html,
                attachments=files, in_reply_to=original.get("message_id"), references=references)
        except ValueError as e:
            raise ValueError(f"The message can't be written as given: {e}") from None

        def deliver(connections):
            refused = mailbox.send(account, connections, message, everyone)
            sent_copy = sent_error = None
            if op.save_to_sent:
                try:
                    with mailbox.Imap(account, connections) as imap:
                        sent_copy = _sent_folder(imap.folders())
                        if sent_copy:
                            imap.append(sent_copy, message.as_bytes())
                except MailError as e:
                    sent_error = str(e)
                if not sent_copy and not sent_error:
                    sent_error = "The mailbox has no Sent folder, so no copy was filed."
            return refused, sent_copy, sent_error

        refused, sent_copy, sent_error = await mailbox.run_on_mailbox(deliver, deadline_s=120, what="sending")
        out: Dict[str, Any] = {
            "status": "sent", "message_id": message["Message-ID"], "from": account.email, "to": to, "cc": cc,
            "bcc": bcc, "subject": subject,
        }
        if replying:
            out["in_reply_to"] = original.get("message_id")
            out["thread"] = (references or [None])[0] or original.get("message_id")
        if refused:
            out["refused"] = refused
        if op.save_to_sent:
            out["saved_to"] = sent_copy if not sent_error else None
            if sent_error:
                out["sent_copy_error"] = sent_error
        return out

    async def _poll(self, op: ImapOnNewEmailConfig, account) -> Dict[str, Any]:
        def candidates(connections):
            with mailbox.Imap(account, connections) as imap:
                state = imap.open(op.folder)
                if state.uidnext:
                    floor = max(1, state.uidnext - TRIGGER_WINDOW_UIDS)
                    window = [(f"UID {floor}:*", None)]
                else:
                    since = date.today() - timedelta(days=14)
                    window, floor = [(f"SINCE {mailbox.imap_date(since)}", None)], 1
                uids = [u for u in imap.search(window + op.criteria()) if u >= floor]
            return state, uids

        state, uids = await mailbox.run_on_mailbox(candidates, deadline_s=60, what="checking for new mail")

        async def prepare(chosen: List[int]) -> Dict[str, Any]:
            def read(connections):
                with mailbox.Imap(account, connections) as imap:
                    again = imap.open(op.folder)
                    if again.uidvalidity != state.uidvalidity:
                        return {}
                    return _read_whole(imap, chosen)

            raw = await mailbox.run_on_mailbox(read, deadline_s=240, what="reading new mail")
            return {f"{state.uidvalidity}:{uid}": await self._message(
                        op.folder, state.uidvalidity, uid, raw[uid], keep=op.download_attachments)
                    for uid in chosen if uid in raw}

        fresh = await self._filter_unseen(
            uids, lambda uid: f"{state.uidvalidity}:{uid}",
            epoch=f"{account.email}|{account.imap.host}|{state.uidvalidity}",
            max_fresh=TRIGGER_MAX_PER_POLL, prepare=prepare,
        )
        return {"account": account.email, "folder": op.folder, "messages": fresh, "new_message_count": len(fresh)}

    async def _message(self, folder: str, uidvalidity: int, uid: int, fetched: Dict[str, Any], *,
                       keep: bool) -> Dict[str, Any]:
        """A message read whole (or, past the size cap, its start) as the node outputs it, its attachments kept."""
        raw = fetched.get("body") or b""
        partial = bool(fetched.get("partial"))
        message, attachments = mailbox.read_message(raw, partial=partial)
        out = {**_message_out(folder, uidvalidity, uid, fetched), **message}
        out["thread"] = mailbox.thread_key(out)
        if partial:
            out["attachments"] = []
            out["attachments_note"] = (f"This message is {_size(fetched.get('size') or 0)}, over the "
                                       f"{_size(mailbox.MAX_MESSAGE_BYTES)} NoClick reads: its text is from its "
                                       "start, and its attachments weren't read.")
            return out
        out["attachments"] = [await self._attachment(a, keep) for a in attachments]
        if attachments and not keep:
            out["attachments_note"] = "Attachments weren't kept as files (Keep attachments as files is off)."
        return out

    async def _attachment(self, attachment: mailbox.Attachment, keep: bool) -> Dict[str, Any]:
        row: Dict[str, Any] = {"filename": attachment.filename, "mime_type": attachment.mime_type,
                               "size_bytes": len(attachment.data), "inline": attachment.inline}
        if attachment.content_id:
            row["content_id"] = attachment.content_id
        if not keep or not attachment.data:
            return row
        slot = await self._keep(attachment)
        if slot:
            row.update({"url": slot["url"], "resource_id": slot["resource_id"], "rehosted": True})
        return row

    async def _keep(self, attachment: mailbox.Attachment) -> Optional[Dict[str, Any]]:
        """An attachment as a file: the workflow's (through the inbound-media seam), else the runner's own."""
        from utils.database_pool import get_native_pool

        if self.workflow_id:
            from utils.inbound_media import store_inbound_media

            return await store_inbound_media(
                get_native_pool(), workflow_id=self.workflow_id, node_id=self.node_id, body=attachment.data,
                source="imap_attachment", mimetype=attachment.mime_type, filename=attachment.filename)
        if not self.user_id:
            return None
        from utils.resource_store import create_resource_from_bytes

        resource = await create_resource_from_bytes(
            user_id=self.user_id, workflow_id=None, node_id=None, organization_id=self.organization_id,
            body=attachment.data, content_type=attachment.mime_type, filename=attachment.filename,
            metadata={"source": "imap_attachment"})
        return {"url": resource["download_url"], "resource_id": resource["resource_id"]}


# ------------------------------------------------------- mailbox helpers


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.0f} MB" if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"


def _with_imap(account, connections, fn):
    with mailbox.Imap(account, connections) as imap:
        return fn(imap)


def _opened(imap: mailbox.Imap, op: _Message, *, write: bool = False) -> mailbox.FolderState:
    state = imap.open(op.folder, write=write)
    if op.uidvalidity is not None and op.uidvalidity != state.uidvalidity:
        raise MailError(f"{op.folder!r} was rebuilt since that UID was read (its UIDVALIDITY changed from "
                        f"{op.uidvalidity} to {state.uidvalidity}), so the UID may name another message. Search "
                        "the folder again.")
    return state


def _require(imap: mailbox.Imap, folder: str, uids: List[int]) -> None:
    present = set(imap.fetch(uids, "(UID)"))
    missing = [u for u in uids if u not in present]
    if missing:
        raise MailError(f"There's no message with UID {', '.join(map(str, missing))} in {folder!r}. Search the "
                        "folder for its UID.")


def _newest_matches(imap: mailbox.Imap, state: mailbox.FolderState, criteria, limit: int) -> List[int]:
    """Matching UIDs, searching the newest UIDs first and widening until there are ``limit`` or the whole folder
    was searched (a SEARCH answer names every match on one line)."""
    top = state.uidnext or 0
    for window in SEARCH_WINDOWS:
        if not top or top - window <= 1:
            break
        floor = top - window
        uids = [u for u in imap.search([(f"UID {floor}:*", None), *criteria]) if u >= floor]
        if len(uids) >= limit:
            return uids
    return imap.search(criteria)


def _read_whole(imap: mailbox.Imap, uids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Each message whole, or past the size cap its first part (marked ``partial``)."""
    sizes = imap.fetch(uids, "(UID FLAGS RFC822.SIZE INTERNALDATE)")
    out: Dict[int, Dict[str, Any]] = {}
    for uid in uids:
        meta = sizes.get(uid)
        if meta is None:
            continue
        too_big = (meta.get("size") or 0) > mailbox.MAX_MESSAGE_BYTES
        part = f"BODY.PEEK[]<0.{mailbox.PARTIAL_BYTES}>" if too_big else "BODY.PEEK[]"
        body = imap.fetch([uid], f"(UID {part})").get(uid, {}).get("body")
        if body is None:
            continue
        out[uid] = {**meta, "body": body, "partial": too_big}
    return out


def _reply_recipients(original: Dict[str, Any], me: str, reply_all: bool) -> Tuple[List[str], List[str]]:
    mine = me.lower()
    to = mailbox.addresses(original.get("reply_to")) or mailbox.addresses(original.get("from"))
    to = [a for a in to if a.lower() != mine] or to
    if not reply_all:
        return to, []
    seen = {a.lower() for a in to} | {mine}
    cc = []
    for a in mailbox.addresses(original.get("to")) + mailbox.addresses(original.get("cc")):
        if a.lower() not in seen:
            seen.add(a.lower())
            cc.append(a)
    return to, cc


_SENT_NAMES = ("sent", "sent messages", "sent items", "sent mail", "inbox.sent", "inbox/sent")


def _sent_folder(folders: List[Dict[str, Any]]) -> Optional[str]:
    marked = next((f["name"] for f in folders if (f.get("special_use") or "").lower() == "sent"), None)
    return marked or next((f["name"] for f in folders if f["name"].lower() in _SENT_NAMES and f["selectable"]), None)
