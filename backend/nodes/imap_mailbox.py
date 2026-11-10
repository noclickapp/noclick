"""A mailbox someone connected over IMAP and SMTP: the servers it lives on, and
everything the IMAP/SMTP node says to them.

Every server is a user-supplied host, so each connection dials an address
``utils.ssrf`` resolved once and judged public (TLS still verifies the host's
own name), only on a mail port, never without TLS, with a timeout on every
socket and a cap on what a server may send back. The protocol work is
blocking (``imaplib``/``smtplib``) and runs in a worker thread through
``run_on_mailbox``, which also bounds it as a whole: a server that trickles
bytes past the deadline has its sockets shut under it.

The password is never logged, never in an exception's text, and never in an
``Account``'s repr.
"""

from __future__ import annotations

import asyncio
import base64
import email
import email.policy
import email.utils
import imaplib
import ipaddress
import logging
import mimetypes
import re
import smtplib
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import EmailMessage, Message
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Ports a mail server answers on. A credential naming any other is refused at
# shaping and again before dialling, so the node can't be pointed at any other
# service on a host.
IMAP_PORTS = {993: "ssl", 143: "starttls"}
SMTP_PORTS = {465: "ssl", 587: "starttls", 25: "starttls", 2525: "starttls"}

SOCKET_TIMEOUT_S = 20.0
# What one server may send back: a response line (a SEARCH answer names every
# matching UID on one line), and one literal (a whole message).
MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_MESSAGE_BYTES = 25 * 1024 * 1024
# What is read of a message too large to read whole, and of each search result for its snippet.
PARTIAL_BYTES = 2 * 1024 * 1024
SNIPPET_READ_BYTES = 32 * 1024
SNIPPET_CHARS = 240
# Text kept of a body in a node's output.
BODY_CHARS = 50_000
MAX_FOLDERS = 2000
MAX_ATTACHMENTS = 25

HEADER_FIELDS = "FROM TO CC REPLY-TO SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES"


class MailError(Exception):
    """A mail server's answer a person can act on, in its own words."""


class MailSignInRefused(MailError):
    """The server refused the sign-in: a verdict about the credential. Its text always says
    "authentication failed", the phrase the connect seam reads as a definitive rejection."""


# ----------------------------------------------------------------- presets


@dataclass(frozen=True)
class Preset:
    provider: str
    imap_host: str
    smtp_host: str
    smtp_port: int = 465
    # Apple signs in to IMAP with the name before the @ (Thunderbird's ISPDB and Apple's own settings page).
    imap_login_local_part: bool = False


_YAHOO = Preset("Yahoo Mail", "imap.mail.yahoo.com", "smtp.mail.yahoo.com")
_AOL = Preset("AOL Mail", "imap.aol.com", "smtp.aol.com")
_ICLOUD = Preset("iCloud Mail", "imap.mail.me.com", "smtp.mail.me.com", 587, imap_login_local_part=True)
_FASTMAIL = Preset("Fastmail", "imap.fastmail.com", "smtp.fastmail.com")
_GMX_COM = Preset("GMX", "imap.gmx.com", "mail.gmx.com")
_GMX_NET = Preset("GMX", "imap.gmx.net", "mail.gmx.net")
_MAIL_COM = Preset("mail.com", "imap.mail.com", "smtp.mail.com")


def _zoho(suffix: str) -> Preset:
    return Preset("Zoho Mail", f"imap.zoho.{suffix}", f"smtp.zoho.{suffix}")


# Settings each provider publishes, as Thunderbird's ISPDB has them. Yahoo Japan
# is a separate company with its own servers and is left to custom settings.
PRESETS: Dict[str, Preset] = {
    **{d: _YAHOO for d in (
        "yahoo.com", "ymail.com", "rocketmail.com", "yahoo.co.uk", "yahoo.ca", "yahoo.com.au", "yahoo.co.in",
        "yahoo.in", "yahoo.fr", "yahoo.de", "yahoo.it", "yahoo.es", "yahoo.ie", "yahoo.co.nz", "yahoo.com.br",
        "yahoo.com.mx", "yahoo.com.ar", "yahoo.com.sg", "yahoo.com.ph", "yahoo.co.id", "yahoo.com.hk",
        "yahoo.com.tw", "yahoo.gr", "yahoo.se", "yahoo.dk", "yahoo.no", "yahoo.fi", "yahoo.at", "yahoo.be",
        "yahoo.pl", "yahoo.ro", "yahoo.co.za", "yahoo.com.vn", "yahoo.co.th", "yahoo.com.my",
    )},
    **{d: _AOL for d in ("aol.com", "aim.com", "aol.co.uk", "aol.de", "aol.fr", "aol.it", "aol.es", "aol.ca",
                         "aol.com.au", "verizon.net", "love.com", "games.com", "wow.com", "ygm.com")},
    **{d: _ICLOUD for d in ("icloud.com", "me.com", "mac.com")},
    **{d: _zoho("com") for d in ("zoho.com", "zohomail.com")},
    **{d: _zoho("eu") for d in ("zoho.eu", "zohomail.eu")},
    **{d: _zoho("in") for d in ("zoho.in", "zohomail.in")},
    **{d: _zoho("com.au") for d in ("zoho.com.au", "zohomail.com.au")},
    "zoho.jp": _zoho("jp"),
    **{d: _FASTMAIL for d in (
        "fastmail.com", "fastmail.fm", "fastmail.net", "fastmail.to", "fastmail.us", "fastmail.cn",
        "fastmail.co.uk", "fastmail.de", "fastmail.es", "fastmail.in", "fastmail.jp", "fastmail.mx",
        "fastmail.se", "messagingengine.com",
    )},
    **{d: _GMX_COM for d in ("gmx.com", "gmx.us", "gmx.co.uk", "gmx.fr", "gmx.es", "gmx.ca", "gmx.it")},
    **{d: _GMX_NET for d in ("gmx.net", "gmx.de", "gmx.at", "gmx.ch")},
    **{d: _MAIL_COM for d in (
        "mail.com", "email.com", "usa.com", "myself.com", "post.com", "consultant.com", "engineer.com",
        "techie.com", "writeme.com", "cheerful.com", "europe.com", "asia.com", "dr.com", "accountant.com",
    )},
}

LOCAL_PART_LOGIN_HOSTS = frozenset(p.imap_host for p in PRESETS.values() if p.imap_login_local_part)

# Mailboxes NoClick connects by signing in with their provider instead: neither
# takes a password from an app here.
SIGN_IN_ELSEWHERE: Dict[str, str] = {
    **{d: "Gmail" for d in ("gmail.com", "googlemail.com")},
    **{d: "Outlook" for d in (
        "outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com", "hotmail.co.uk", "hotmail.fr",
        "hotmail.de", "hotmail.it", "hotmail.es", "live.co.uk", "live.fr", "live.de", "live.ca",
        "outlook.co.uk", "outlook.fr", "outlook.de", "outlook.es", "outlook.it", "outlook.in", "outlook.jp",
    )},
}


def domain_of(address: str) -> str:
    return address.rpartition("@")[2].strip().lower().rstrip(".")


def preset_for(address: str) -> Optional[Preset]:
    return PRESETS.get(domain_of(address))


def default_security(port: int, kind: str) -> str:
    return (IMAP_PORTS if kind == "IMAP" else SMTP_PORTS).get(port, "ssl")


def check_port(port: int, kind: str) -> None:
    allowed = IMAP_PORTS if kind == "IMAP" else SMTP_PORTS
    if port not in allowed:
        raise ValueError(f"{kind} port must be one a mail server uses: {', '.join(map(str, allowed))}.")


# ------------------------------------------------------------ the servers


@dataclass(frozen=True)
class Server:
    kind: str  # "IMAP" | "SMTP"
    host: str
    port: int
    security: str  # "ssl" | "starttls"
    login: str
    address: str  # the IP utils.ssrf resolved and judged for this host


@dataclass(frozen=True)
class Account:
    email: str
    imap: Server
    smtp: Server
    password: str = field(repr=False)


async def resolve_account(*, email_address: str, password: str, imap: Tuple[str, int, str, str],
                          smtp: Tuple[str, int, str, str]) -> Account:
    """The account with each host resolved once and judged public (``utils.ssrf``)."""
    from utils.ssrf import resolve_host_addresses

    async def server(kind: str, spec: Tuple[str, int, str, str]) -> Server:
        host, port, security, login = spec
        check_port(port, kind)
        try:
            addresses = await resolve_host_addresses(host, port)
        except ValueError as e:
            raise MailError(f"Can't reach the {kind} server {host}: {e}") from None
        return Server(kind, host, port, security, login, addresses[0])

    imap_server, smtp_server = await asyncio.gather(server("IMAP", imap), server("SMTP", smtp))
    return Account(email_address, imap_server, smtp_server, password)


class _Connections:
    """The sockets one piece of mail work opened, each watched (as a duplicate) from the moment it connects, so
    a deadline can shut them under a thread blocked in a handshake or a read."""

    def __init__(self) -> None:
        self._watched: List[socket.socket] = []
        self._lock = threading.Lock()
        self.expired = False

    def watch(self, sock: socket.socket) -> None:
        with self._lock:
            if self.expired:
                sock.close()
                raise MailError("The mail server didn't finish in time.")
            self._watched.append(sock.dup())

    def shut(self) -> None:
        with self._lock:
            self.expired = True
            watched = list(self._watched)
        for sock in watched:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            watched, self._watched = self._watched, []
        for sock in watched:
            sock.close()


async def run_on_mailbox(work: Callable[[_Connections], T], *, deadline_s: float, what: str) -> T:
    """``work`` in a worker thread (the loop stays free), bounded as a whole by ``deadline_s``."""
    connections = _Connections()
    try:
        return await asyncio.wait_for(asyncio.to_thread(work, connections), deadline_s)
    except asyncio.TimeoutError:
        connections.shut()
        raise MailError(f"The mail server didn't finish {what} within {int(deadline_s)} seconds.") from None
    finally:
        connections.close()


def _words(e: BaseException) -> str:
    """A server's words out of an imaplib/smtplib error, which carry bytes."""
    if isinstance(e, smtplib.SMTPResponseException):
        text = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        return f"{e.smtp_code} {text}".strip()
    arg = e.args[0] if e.args else str(e)
    if isinstance(arg, bytes):
        arg = arg.decode(errors="replace")
    text = str(arg)
    if text.startswith(("b'", 'b"')) and text.endswith(("'", '"')):
        text = text[2:-1]
    return text.strip()


def _transport_error(server: Server, e: BaseException) -> MailError:
    if isinstance(e, ssl.SSLCertVerificationError):
        return MailError(f"{server.host} presented a certificate that couldn't be verified: {e.verify_message}.")
    if isinstance(e, (socket.timeout, TimeoutError)):
        return MailError(f"The {server.kind} server {server.host}:{server.port} didn't answer in time.")
    if isinstance(e, ssl.SSLError):
        return MailError(f"TLS with {server.host}:{server.port} failed ({e.reason or e}). Check the port and its "
                         "security setting.")
    if isinstance(e, OSError):
        return MailError(f"Couldn't connect to the {server.kind} server {server.host}:{server.port}: "
                         f"{e.strerror or e}.")
    return MailError(f"The {server.kind} server {server.host} answered: {_words(e)}")


def _refused(server: Server, words: str) -> MailSignInRefused:
    return MailSignInRefused(
        f"The {server.kind} server {server.host} refused the sign-in for {server.login} (authentication failed): "
        f"{words or 'no reason given'}"
    )


# ------------------------------------------------------------------- IMAP


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def encode_folder(name: str) -> str:
    """A folder's name as IMAP spells it (modified UTF-7, RFC 3501 5.1.3)."""
    out: List[str] = []
    pending: List[str] = []

    def flush() -> None:
        if pending:
            raw = "".join(pending).encode("utf-16-be")
            out.append("&" + base64.b64encode(raw).decode().rstrip("=").replace("/", ",") + "-")
            pending.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            pending.append(ch)
    flush()
    return "".join(out)


def decode_folder(name: str) -> str:
    def plain(match: "re.Match[str]") -> str:
        chunk = match.group(1)
        if not chunk:
            return "&"
        chunk = chunk.replace(",", "/")
        try:
            return base64.b64decode(chunk + "=" * (-len(chunk) % 4)).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return match.group(0)

    return re.sub(r"&([A-Za-z0-9+,]*)-", plain, name)


class _Capped:
    """What a server may send: no line past ``MAX_LINE_BYTES``, no literal past a message's cap."""

    def readline(self) -> bytes:
        line = self.file.readline(MAX_LINE_BYTES + 1)
        if len(line) > MAX_LINE_BYTES:
            raise self.error(f"the server sent a line over {MAX_LINE_BYTES} bytes")
        return line

    def read(self, size: int) -> bytes:
        if size > MAX_MESSAGE_BYTES + 64 * 1024:
            raise self.error(f"the server sent {size} bytes at once, over the {MAX_MESSAGE_BYTES} NoClick reads")
        return super().read(size)


class _IMAP(_Capped, imaplib.IMAP4):
    """Dials the resolved address; TLS (STARTTLS) still verifies the host's name."""

    def __init__(self, server: Server, timeout: float, connections: "_Connections"):
        self._address, self._connections = server.address, connections
        super().__init__(server.host, server.port, timeout=timeout)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self._address, self.port), timeout)
        self._connections.watch(sock)
        return sock


class _IMAPS(_Capped, imaplib.IMAP4_SSL):
    def __init__(self, server: Server, timeout: float, connections: "_Connections", context: ssl.SSLContext):
        self._address, self._connections = server.address, connections
        super().__init__(server.host, server.port, ssl_context=context, timeout=timeout)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self._address, self.port), timeout)
        self._connections.watch(sock)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


_TRANSIENT_CODES = ("[UNAVAILABLE]", "[INUSE]", "[SERVERBUG]", "[LIMIT]")


@dataclass
class FolderState:
    name: str
    uidvalidity: int
    uidnext: Optional[int]
    exists: int


class Imap:
    """One signed-in IMAP connection, used from a worker thread."""

    def __init__(self, account: Account, connections: _Connections, *, timeout: float = SOCKET_TIMEOUT_S):
        from utils.smtp_transport import tls_context

        server = account.imap
        self.server = server
        try:
            if server.security == "ssl":
                client: imaplib.IMAP4 = _IMAPS(server, timeout, connections, tls_context())
            else:
                client = _IMAP(server, timeout, connections)
                if "STARTTLS" not in client.capabilities:
                    client.shutdown()
                    raise MailError(f"{server.host} doesn't offer STARTTLS on port {server.port}, so the password "
                                    "would cross the network unencrypted. Use its SSL/TLS port (usually 993).")
                client.starttls(tls_context())
        except MailError:
            raise
        except (OSError, imaplib.IMAP4.error) as e:
            raise _transport_error(server, e) from None
        self.client = client
        try:
            user = server.login
            if any(ord(ch) > 127 for ch in user + account.password):
                secret = account.password
                client.authenticate("PLAIN", lambda _: f"\0{user}\0{secret}".encode())
            else:
                client.login(quote(user), account.password)
        except (imaplib.IMAP4.abort, OSError) as e:  # a dropped connection is no verdict on the password
            self.close()
            raise _transport_error(server, e) from None
        except imaplib.IMAP4.error as e:
            self.close()
            words = _words(e)
            if any(code in words.upper() for code in _TRANSIENT_CODES):
                raise MailError(f"{server.host} can't take a sign-in right now: {words}") from None
            raise _refused(server, words) from None
        # A server names more once signed in (MOVE, UIDPLUS), so ask again.
        try:
            typ, data = client.capability()
            words = data[-1].decode(errors="replace").split() if typ == "OK" and data and data[-1] else []
        except (imaplib.IMAP4.error, OSError):
            words = []
        self.capabilities = {c.upper() for c in (words or client.capabilities)}

    def close(self) -> None:
        try:
            self.client.logout()
        except Exception:
            try:
                self.client.shutdown()
            except Exception:
                pass

    def __enter__(self) -> "Imap":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _ok(self, typ: str, data: Any, doing: str) -> Any:
        if typ != "OK":
            words = " ".join(_words(Exception(d)) for d in data if d) if isinstance(data, list) else str(data)
            raise MailError(f"{self.server.host} refused to {doing}: {words or typ}")
        return data

    def _call(self, fn: Callable[..., Tuple[str, Any]], *args: Any, doing: str) -> Any:
        try:
            typ, data = fn(*args)
        except imaplib.IMAP4.abort as e:
            raise MailError(
                f"The connection to {self.server.host} dropped while trying to {doing}: {_words(e)}") from None
        except imaplib.IMAP4.error as e:
            raise MailError(f"{self.server.host} refused to {doing}: {_words(e)}") from None
        except OSError as e:
            raise _transport_error(self.server, e) from None
        return self._ok(typ, data, doing)

    # ---- folders

    def folders(self) -> List[Dict[str, Any]]:
        data = self._call(self.client.list, '""', '"*"', doing="list its folders")
        out: List[Dict[str, Any]] = []
        for item in data:
            if item is None:
                continue
            if isinstance(item, tuple):
                head, literal = item
                line = head.decode(errors="replace")
                name = literal.decode(errors="replace")
                match = re.match(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)', line)
            else:
                line = item.decode(errors="replace")
                match = re.match(
                    r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.+)$', line)
                if not match:
                    continue
                name = match.group("name").strip()
                if name.startswith('"') and name.endswith('"'):
                    name = re.sub(r'\\(.)', r'\1', name[1:-1])
            if not match:
                continue
            flags = match.group("flags").split()
            delim = match.group("delim")
            out.append({
                "name": decode_folder(name),
                "flags": flags,
                "delimiter": None if delim == "NIL" else re.sub(r'\\(.)', r'\1', delim[1:-1]),
                "selectable": not any(f.lower() == "\\noselect" for f in flags),
                "special_use": next((f[1:] for f in flags if f.lower() in (
                    "\\sent", "\\trash", "\\drafts", "\\junk", "\\archive", "\\all", "\\flagged")), None),
            })
            if len(out) >= MAX_FOLDERS:
                break
        return out

    def open(self, folder: str, *, write: bool = False) -> FolderState:
        try:
            typ, data = self.client.select(quote(encode_folder(folder)), readonly=not write)
        except imaplib.IMAP4.abort as e:
            raise MailError(f"The connection to {self.server.host} dropped while opening {folder!r}: "
                            f"{_words(e)}") from None
        except imaplib.IMAP4.error as e:
            raise MailError(f"{self.server.host} couldn't open the folder {folder!r}: {_words(e)}") from None
        except OSError as e:
            raise _transport_error(self.server, e) from None
        if typ != "OK":
            raise MailError(f"There's no folder {folder!r} in this mailbox ({_words(Exception(data[-1]))}). "
                            "List the folders to see their names.")
        untagged = self.client.untagged_responses
        uidvalidity = _int(untagged.get("UIDVALIDITY", [None])[-1])
        if uidvalidity is None:
            raise MailError(f"{self.server.host} didn't say the folder's UIDVALIDITY.")
        return FolderState(folder, uidvalidity, _int(untagged.get("UIDNEXT", [None])[-1]),
                           _int(untagged.get("EXISTS", [b"0"])[-1]) or 0)

    # ---- search

    def search(self, criteria: Sequence[Tuple[str, Optional[str]]]) -> List[int]:
        """UIDs matching every ``(keyword, value)``: a value is sent as a string, and None sends the keyword as
        written (``UNSEEN``, ``UID 100:*``, ``SINCE 1-Nov-2026``). A value outside ASCII is
        sent as a UTF-8 literal, which imaplib places last, one per command: each one is searched on its own
        beside the plain terms, and the answers intersected."""
        plain: List[str] = []
        wide: List[Tuple[str, str]] = []
        for keyword, value in criteria:
            if value is None:
                plain.append(keyword)
            elif value.isascii():
                plain += [keyword, quote(value)]
            else:
                wide.append((keyword, value))
        if not wide:
            return self._search(plain or ["ALL"])
        found: Optional[set] = None
        for keyword, value in wide:
            self.client.literal = value.encode("utf-8")
            uids = set(self._search(["CHARSET", "UTF-8", *plain, keyword]))
            found = uids if found is None else found & uids
        return sorted(found or ())

    def _search(self, args: List[str]) -> List[int]:
        data = self._call(lambda *a: self.client.uid("SEARCH", *a), *args, doing="search the folder")
        uids: List[int] = []
        for line in data:
            if line:
                uids += [int(token) for token in line.split() if token.isdigit()]
        return sorted(set(uids))

    # ---- fetch

    def fetch(self, uids: Sequence[int], items: str) -> Dict[int, Dict[str, Any]]:
        """``{uid: {"meta": text, "header": bytes, "body": bytes}}`` for a UID FETCH of ``items``."""
        if not uids:
            return {}
        data = self._call(lambda *a: self.client.uid("FETCH", *a), _uid_set(uids), items, doing="read messages")
        return _parse_fetch(data)

    def flag_seen(self, uids: Sequence[int], seen: bool) -> None:
        op = "+FLAGS.SILENT" if seen else "-FLAGS.SILENT"
        self._call(lambda *a: self.client.uid("STORE", *a), _uid_set(uids), op, r"(\Seen)",
                   doing="change the messages' read state")

    def move(self, uids: Sequence[int], destination: str) -> None:
        target = quote(encode_folder(destination))
        if "MOVE" in self.capabilities:
            self._call(lambda *a: self.client.uid("MOVE", *a), _uid_set(uids), target,
                       doing=f"move the messages to {destination!r}")
            return
        if "UIDPLUS" not in self.capabilities:
            raise MailError(f"{self.server.host} can't move a message (it has neither MOVE nor UIDPLUS), and moving "
                            "by copy and expunge could permanently remove other messages, so nothing was moved.")
        self._call(lambda *a: self.client.uid("COPY", *a), _uid_set(uids), target,
                   doing=f"copy the messages to {destination!r}")
        self._call(lambda *a: self.client.uid("STORE", *a), _uid_set(uids), "+FLAGS.SILENT", r"(\Deleted)",
                   doing="mark the copied messages")
        self._call(lambda *a: self.client.uid("EXPUNGE", *a), _uid_set(uids), doing="finish the move")

    def append(self, folder: str, raw: bytes, flags: str = r"(\Seen)") -> None:
        self._call(self.client.append, quote(encode_folder(folder)), flags,
                   imaplib.Time2Internaldate(time.time()), raw, doing=f"file a copy in {folder!r}")


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _uid_set(uids: Iterable[int]) -> str:
    return ",".join(str(int(u)) for u in uids)


_MESSAGE_START = re.compile(rb"^\s*\d+ \(")


def _parse_fetch(data: List[Any]) -> Dict[int, Dict[str, Any]]:
    """imaplib's FETCH answer — literals as (prefix, bytes) tuples, the rest as bytes, a message's parts
    spread over several items — regrouped per message."""
    messages: List[Dict[str, Any]] = []
    for item in data:
        if item is None:
            continue
        prefix = item[0] if isinstance(item, tuple) else item
        if not isinstance(prefix, bytes):
            continue
        if _MESSAGE_START.match(prefix) or not messages:
            messages.append({"meta": b"", "header": None, "body": None})
        current = messages[-1]
        current["meta"] += prefix + b" "
        if isinstance(item, tuple):
            section = re.findall(rb"BODY\[([^\]]*)\]", prefix)
            key = "header" if section and b"HEADER" in section[-1].upper() else "body"
            current[key] = item[1]
    out: Dict[int, Dict[str, Any]] = {}
    for message in messages:
        meta = message["meta"].decode(errors="replace")
        uid = re.search(r"\bUID (\d+)", meta)
        if not uid:
            continue
        size = re.search(r"\bRFC822\.SIZE (\d+)", meta)
        flags = re.search(r"\bFLAGS \(([^)]*)\)", meta)
        internal = re.search(r'\bINTERNALDATE "([^"]+)"', meta)
        out[int(uid.group(1))] = {
            "size": int(size.group(1)) if size else None,
            "flags": flags.group(1).split() if flags else [],
            "internal_date": _internal_date(internal.group(1)) if internal else None,
            "header": message["header"],
            "body": message["body"],
        }
    return out


def _internal_date(text: str) -> Optional[str]:
    try:
        return datetime.strptime(text.strip(), "%d-%b-%Y %H:%M:%S %z").isoformat()
    except ValueError:
        return None


def imap_date(day: date) -> str:
    return f"{day.day}-{('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())[day.month - 1]}-{day.year}"


# ------------------------------------------------------------------- SMTP


def send(account: Account, connections: _Connections, message: EmailMessage, recipients: List[str],
         *, timeout: float = SOCKET_TIMEOUT_S) -> Dict[str, Any]:
    """Send over the account's SMTP server, signed in as the account. Returns refusals by address."""
    from utils.smtp_transport import TlsUnavailable, smtp_client

    server = account.smtp
    try:
        client = smtp_client(server.host, server.port, timeout, security=server.security, address=server.address,
                             on_socket=connections.watch)
    except TlsUnavailable as e:
        raise MailError(str(e)) from None
    except (OSError, smtplib.SMTPException) as e:
        raise _transport_error(server, e) from None
    try:
        _sign_in(client, server, account.password)
        refused = client.send_message(message, from_addr=account.email, to_addrs=recipients)
        return {addr: f"{code} {_decode(text)}" for addr, (code, text) in (refused or {}).items()}
    except smtplib.SMTPRecipientsRefused as e:
        raise MailError(f"{server.host} refused every recipient: " + "; ".join(
            f"{addr}: {code} {_decode(text)}" for addr, (code, text) in e.recipients.items())) from None
    except smtplib.SMTPResponseException as e:
        raise MailError(f"{server.host} refused the message: {_words(e)}") from None
    except (OSError, smtplib.SMTPException) as e:
        raise _transport_error(server, e) from None
    finally:
        _quit(client)


def check_smtp(account: Account, connections: _Connections, *, timeout: float = SOCKET_TIMEOUT_S) -> None:
    """Sign in to the SMTP server the way a send would, sending nothing."""
    from utils.smtp_transport import TlsUnavailable, smtp_client

    server = account.smtp
    try:
        client = smtp_client(server.host, server.port, timeout, security=server.security, address=server.address,
                             on_socket=connections.watch)
    except TlsUnavailable as e:
        raise MailError(str(e)) from None
    except (OSError, smtplib.SMTPException) as e:
        raise _transport_error(server, e) from None
    try:
        _sign_in(client, server, account.password)
    except (OSError, smtplib.SMTPException) as e:
        raise _transport_error(server, e) from None
    finally:
        _quit(client)


def _sign_in(client: smtplib.SMTP, server: Server, password: str) -> None:
    try:
        client.login(server.login, password)
    except smtplib.SMTPAuthenticationError as e:
        raise _refused(server, _words(e)) from None
    except smtplib.SMTPNotSupportedError:
        raise MailError(f"{server.host} doesn't take a sign-in on port {server.port}. Use its submission port "
                        "(465 or 587).") from None


def _quit(client: smtplib.SMTP) -> None:
    try:
        client.quit()
    except Exception:
        client.close()


def _decode(text: Any) -> str:
    return text.decode(errors="replace") if isinstance(text, bytes) else str(text)


# ------------------------------------------------------------- messages


def parse(raw: bytes) -> Message:
    return email.message_from_bytes(raw, policy=email.policy.default)


def _header(msg: Message, name: str) -> Optional[str]:
    try:
        value = msg.get(name)
    except Exception:  # a header the parser can't read is no header
        return None
    return " ".join(str(value).split()) if value is not None else None


def addresses(value: Optional[str]) -> List[str]:
    return [addr for _, addr in email.utils.getaddresses([value or ""]) if "@" in addr]


def message_ids(value: Optional[str]) -> List[str]:
    return re.findall(r"<[^<>\s]+>", value or "")


def headers_of(msg: Message) -> Dict[str, Any]:
    sender = _header(msg, "From")
    date_header = _header(msg, "Date")
    try:
        sent_at = email.utils.parsedate_to_datetime(date_header).isoformat() if date_header else None
    except (TypeError, ValueError):
        sent_at = None
    return {
        "from": sender,
        "from_address": (addresses(sender) or [None])[0],
        "to": _header(msg, "To"),
        "cc": _header(msg, "Cc"),
        "reply_to": _header(msg, "Reply-To"),
        "subject": _header(msg, "Subject"),
        "date": sent_at or date_header,
        "message_id": (message_ids(_header(msg, "Message-ID")) or [None])[0],
        "in_reply_to": (message_ids(_header(msg, "In-Reply-To")) or [None])[0],
        "references": message_ids(_header(msg, "References")),
    }


def thread_key(headers: Dict[str, Any]) -> Optional[str]:
    """The message that started a thread: the first References entry, else what it answers, else itself."""
    refs = headers.get("references") or []
    return (refs[0] if refs else None) or headers.get("in_reply_to") or headers.get("message_id")


def _content(part: Message) -> Optional[str]:
    try:
        content = part.get_content()
    except (LookupError, ValueError, AssertionError, KeyError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return content if isinstance(content, str) else None


def html_text(html: str) -> str:
    from utils.email_body import html_text as readable

    return readable(html)


def snippet(msg: Message) -> str:
    """The first words a person would read, from a message read whole or in part."""
    body = None
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
    except Exception:
        body = None
    text = (_content(body) or "") if body is not None else ""
    if body is not None and body.get_content_subtype() == "html":
        text = html_text(text)
    text = " ".join(text.split())
    return text[:SNIPPET_CHARS] + ("…" if len(text) > SNIPPET_CHARS else "")


def _clip(text: Optional[str]) -> Tuple[Optional[str], bool]:
    if text is None or len(text) <= BODY_CHARS:
        return text, False
    return text[:BODY_CHARS], True


@dataclass
class Attachment:
    filename: str
    mime_type: str
    data: bytes = field(repr=False)
    inline: bool = False
    content_id: Optional[str] = None


def _safe_name(name: Optional[str], mime: str, n: int) -> str:
    base = re.sub(r"[\x00-\x1f/\\]+", "_", (name or "").strip()).strip(". ") or ""
    if not base:
        base = f"attachment-{n}{mimetypes.guess_extension(mime) or ''}"
    return base[:180]


def bodies_and_attachments(msg: Message) -> Tuple[Optional[str], Optional[str], List[Attachment]]:
    """The text and HTML a person reads, and every other part as an attachment (a forwarded message whole)."""
    text_part = html_part = None
    try:
        text_part = msg.get_body(preferencelist=("plain",))
        html_part = msg.get_body(preferencelist=("html",))
    except Exception:
        pass
    attachments: List[Attachment] = []

    def visit(part: Message) -> None:
        if len(attachments) >= MAX_ATTACHMENTS:
            return
        if part is text_part or part is html_part:
            return
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else inner
            raw = inner.as_bytes() if isinstance(inner, Message) else (part.get_payload(decode=True) or b"")
            subject = inner.get("Subject") if isinstance(inner, Message) else None
            attachments.append(Attachment(_safe_name(f"{subject or 'message'}.eml", ctype, len(attachments) + 1),
                                          ctype, raw))
            return
        if part.is_multipart():
            for sub in part.iter_parts():
                visit(sub)
            return
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if not filename and disposition != "attachment" and part.get_content_maintype() == "text":
            return  # an alternative body the reader already has
        data = part.get_payload(decode=True) or b""
        cid = _header(part, "Content-ID")
        attachments.append(Attachment(_safe_name(filename, ctype, len(attachments) + 1), ctype, data,
                                      inline=disposition == "inline" or (not filename and bool(cid)),
                                      content_id=(cid or "").strip("<>") or None))

    visit(msg)
    text = _content(text_part) if text_part is not None else None
    html = _content(html_part) if html_part is not None else None
    return (text.rstrip() if text else text), (html.rstrip() if html else html), attachments


def read_message(raw: bytes, *, partial: bool = False) -> Tuple[Dict[str, Any], List[Attachment]]:
    """A message as the node shows it, and its attachments' bytes to keep."""
    msg = parse(raw)
    text, html, attachments = bodies_and_attachments(msg)
    if text is None and html is not None:
        text = html_text(html)
    text, text_cut = _clip(text)
    html, html_cut = _clip(html)
    out = {**headers_of(msg), "text": text, "html": html, "snippet": snippet(msg)}
    if text_cut or html_cut:
        out["body_truncated"] = True
    if partial:
        attachments = []
    return out, attachments


# -------------------------------------------------------------- composing


def compose(*, sender: str, from_name: Optional[str], to: List[str], cc: List[str], subject: str,
            text: Optional[str], html: Optional[str], attachments: Sequence[Tuple[str, str, bytes]] = (),
            in_reply_to: Optional[str] = None, references: Sequence[str] = ()) -> EmailMessage:
    """A message from the connected mailbox. Header values can't carry a line break (``email.policy`` refuses
    one), so no field can add a header of its own."""
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"] = email.utils.formataddr((from_name, sender)) if from_name else sender
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=False)
    msg["Message-ID"] = email.utils.make_msgid(domain=domain_of(sender) or None)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)
    plain = text if text is not None else html_text(html or "")
    msg.set_content(plain)
    if html:
        msg.add_alternative(html, subtype="html")
    for filename, mime, data in attachments:
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
    return msg


def is_public_host(host: str) -> bool:
    """Shape-time judgement of a host with no lookup: an IP literal must be public, and names that only
    resolve inside a network (``localhost``, ``.local``, ``.internal``) are refused. ``utils.ssrf`` judges
    every name again, resolved, before any connection."""
    from utils.ssrf import allow_private_hosts, is_blocked_ip

    if allow_private_hosts():
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return not (host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")))
    return not is_blocked_ip(host)
