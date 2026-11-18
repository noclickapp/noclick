"""The ``noclick`` command: a thin layer over this package for the terminal.

    noclick login
    noclick agents chat support-bot --user user_42
    noclick machines ssh support-box
    noclick deploy

Each command is a few client calls, written the way your own code would make
them.

The key comes from ``NOCLICK_API_KEY`` when it's set (CI), else from what
``noclick login`` stored for the profile (``--profile`` or ``NOCLICK_PROFILE``).
``noclick deploy --token`` takes the deploy token NoClick's MCP server hands an
agent instead.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import httpx

from ._client import API_KEY_ENV, API_URL_ENV, DEFAULT_BASE_URL, Client, configure
from ._object import UNSET
from ._sync import run_sync
from ._scope import ALL_USERS, as_user
from ._version import __version__
from .agent import Agent
from .agent_move import AgentMove
from .bucket import Bucket
from .database import Database
from .domain import Domain, DomainContact
from .exceptions import Conflict, Error, InvalidRequest, NotFound, OperationFailed, OperationTimeout, Unauthenticated
from .machine import Machine
from .operation import Operation
from .project import Deployment, Project
from .repo import Repo
from .user import User
from .webhook import SIGNATURE_HEADER, Event

PROFILE_ENV = "NOCLICK_PROFILE"
CONFIG_DIR_ENV = "NOCLICK_CONFIG_DIR"
KEYCHAIN_SERVICE = "noclick"
USER_AGENT = f"noclick-cli/{__version__}"

# Polling cadence for `logs --follow` and `webhooks listen`; tests replace _sleep.
POLL_S = 2.0
_sleep: Callable[[float], None] = time.sleep


class CommandError(Error):
    """A problem the CLI found on your machine (not an API refusal)."""

    type = "command_error"


def _note(message: str) -> None:
    """Progress and hints go to stderr, so stdout stays clean for pipes."""
    print(message, file=sys.stderr)


# --- credentials -------------------------------------------------------------


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "noclick"


def _read_config() -> Dict[str, Any]:
    path = config_dir() / "config.json"
    return json.loads(path.read_text()) if path.exists() else {"profiles": {}}


def _write_private(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=2)


def _write_config(config: Dict[str, Any]) -> None:
    _write_private(config_dir() / "config.json", config)


def _keyring() -> Any:
    try:
        import keyring
    except ImportError:
        raise CommandError(
            "No OS keychain library is installed.",
            next_step="pip install 'noclick[cli]', or pass --store file to keep the key in a file only you can read.",
        ) from None
    return keyring


class KeychainStore:
    """The OS keychain (macOS Keychain, Windows Credential Manager, Secret Service)."""

    name = "keychain"

    def __init__(self) -> None:
        self._keyring = _keyring()

    def _call(self, method: str, *args: str) -> Any:
        try:
            return getattr(self._keyring, method)(KEYCHAIN_SERVICE, *args)
        except self._keyring.errors.KeyringError as exc:
            raise CommandError(
                f"The OS keychain refused: {exc}",
                next_step="Unlock the keychain and retry, or pass --store file.",
            ) from exc

    def read(self, profile: str) -> Optional[str]:
        return self._call("get_password", profile)

    def write(self, profile: str, key: str) -> None:
        self._call("set_password", profile, key)

    def delete(self, profile: str) -> None:
        if self.read(profile) is not None:
            self._call("delete_password", profile)


class FileStore:
    """``credentials.json`` in the config directory, readable only by you."""

    name = "file"

    @property
    def path(self) -> Path:
        return config_dir() / "credentials.json"

    def _all(self) -> Dict[str, str]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def read(self, profile: str) -> Optional[str]:
        return self._all().get(profile)

    def write(self, profile: str, key: str) -> None:
        _write_private(self.path, {**self._all(), profile: key})

    def delete(self, profile: str) -> None:
        keys = self._all()
        if keys.pop(profile, None) is not None:
            _write_private(self.path, keys)


def key_store(name: str) -> Any:
    return KeychainStore() if name == "keychain" else FileStore()


@dataclass
class Credentials:
    """What the next command signs in with, and where it came from."""

    key: Optional[str]
    source: str  # "env", "keychain", "file" or "none"
    profile: str
    api_url: str
    login: Dict[str, Any] = field(default_factory=dict)  # what `noclick login` recorded for the profile


def resolve_credentials(profile: str) -> Credentials:
    """``NOCLICK_API_KEY`` wins (CI); else the profile's stored key, on the API it was minted for."""
    login = _read_config().get("profiles", {}).get(profile, {})
    env_key = os.environ.get(API_KEY_ENV)
    if env_key:
        return Credentials(env_key, "env", profile, os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL, login)
    if login.get("store"):
        key = key_store(login["store"]).read(profile)
        if key:
            return Credentials(key, login["store"], profile, login.get("api_url") or DEFAULT_BASE_URL, login)
    return Credentials(None, "none", profile, os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL, login)


def _signed_in(profile: str) -> Credentials:
    creds = resolve_credentials(profile)
    if not creds.key:
        raise Unauthenticated(
            "You're not signed in.", next_step=f"Run noclick login, or set {API_KEY_ENV}.",
        )
    return creds


def _mask(key: str) -> str:
    return f"{key[:12]}…"


# --- output ------------------------------------------------------------------


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(value)


def _table(headers: Sequence[str], rows: Iterable[Sequence[Any]], *, empty: str) -> None:
    cells = [[_cell(v) for v in row] for row in rows]
    if not cells:
        _note(empty)
        return
    widths = [max(len(h), *(len(row[i]) for row in cells)) for i, h in enumerate(headers)]
    for row in [list(headers), *cells]:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())


def _plain(item: Any) -> Any:
    """Objects and records as JSON-ready data: each one's server JSON when it has one."""
    if isinstance(item, list):
        return [_plain(i) for i in item]
    raw = getattr(item, "raw", None)
    if isinstance(raw, dict):
        return raw
    if is_dataclass(item) and not isinstance(item, type):
        return asdict(item)
    return item


def _print_json(data: Any) -> None:
    print(json.dumps(_plain(data), indent=2, default=str))


def _size(n: Optional[int]) -> str:
    if n is None:
        return "-"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return str(n)


def _usd(value: Optional[float]) -> str:
    return "-" if value is None else f"${value:,.2f}"


def _since(text: str) -> datetime:
    """``--since``: ``15m``, ``2h``, ``1d`` or ``30s`` ago, or an ISO time (UTC unless it says otherwise)."""
    match = re.fullmatch(r"(\d+)([smhd])", text)
    if match:
        seconds = int(match.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
        return datetime.now(timezone.utc) - timedelta(seconds=seconds)
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError("use 15m, 2h, 1d or an ISO time like 2026-09-28T09:00") from None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _value(text: str) -> Any:
    """A query parameter from the command line: JSON when it parses (``42``, ``null``), else the text."""
    try:
        return json.loads(text)
    except ValueError:
        return text


# --- sign in -----------------------------------------------------------------


def _anonymous_post(http: httpx.Client, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """The two sign-in calls run before there is a key, so they skip the SDK client."""
    response = http.post(path, json=body, headers={"Idempotency-Key": f"nc_{uuid.uuid4().hex}"})
    return Client._decode(response) or {}


def cmd_login(args: argparse.Namespace) -> int:
    store = key_store(args.store)  # refuse a missing keychain before the browser opens
    api_url = (os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
    with httpx.Client(base_url=api_url, timeout=30, headers={"User-Agent": USER_AGENT}) as http:
        start = _anonymous_post(http, "/v1/cli/logins", {"client": "noclick-cli", "hostname": socket.gethostname()})
        link = start.get("verification_url_complete") or start["verification_url"]
        # Flushed: a piped stdout (an agent's shell, CI) would otherwise hold it until the sign-in ends.
        print(f"Open {start['verification_url']} and enter the code {start['user_code']}", flush=True)
        if not args.no_browser and sys.stdin.isatty():
            webbrowser.open(link)
        interval = start.get("interval_s") or 5
        while True:
            _sleep(interval)
            poll = _anonymous_post(http, "/v1/cli/logins/token", {"device_code": start["device_code"]})
            if poll.get("status") == "approved":
                break
            interval = poll.get("interval_s") or interval
    store.write(args.profile, poll["key"])
    config = _read_config()
    config.setdefault("profiles", {})[args.profile] = {
        "api_url": api_url, "store": store.name, "key_id": poll.get("key_id"), "key_name": poll.get("key_name"),
        "key_prefix": poll["key"][:12], "email": poll.get("email"),
    }
    _write_config(config)
    where = "the OS keychain" if store.name == "keychain" else str(FileStore().path)
    print(f"Signed in as {poll.get('email') or 'your account'}.")
    _note(f"The key \"{poll.get('key_name')}\" is in {where}. noclick logout revokes it.")
    return 0


def _signed_in_as(account: Dict[str, Any]) -> Tuple[str, str]:
    """The row naming who the key acts as, from ``GET /v1/status``'s ``account``: the account, or the user a key
    acting for one of the account's users acts for."""
    user = account.get("acting_for")
    if user:
        known = ", ".join(v for v in (user.get("name"), user.get("email")) if v)
        return "User", f"{user['id']}{f' ({known})' if known else ''}: the key acts for this user, not the account"
    known = ", ".join(v for v in (account.get("name"), account.get("email")) if v)
    return "Account", f"{known} ({account['id']})" if known else account["id"]


def cmd_whoami(args: argparse.Namespace) -> int:
    creds = _signed_in(args.profile)
    login = creds.login if creds.source != "env" else {}
    source = {"env": f"from {API_KEY_ENV}", "keychain": "in the OS keychain", "file": "in a file"}[creds.source]
    if creds.source == "env" and creds.login.get("store"):
        _note(f"{API_KEY_ENV} overrides the login stored for this profile ({creds.login.get('email')}).")
    name = f"{login['key_name']} ({_mask(creds.key)})" if login.get("key_name") else _mask(creds.key)
    rows = [("Key", f"{name}, {source}"), ("Profile", creds.profile), ("API", creds.api_url)]
    # The account the key is in, as the API says: what was stored at login can name another one.
    client = Client(api_key=creds.key, base_url=creds.api_url)
    try:
        account = run_sync(client.request("GET", "/v1/status", user=None))["account"]
    except Error:
        if not args.json:
            _print_rows(rows)  # which key the API refused
        raise
    finally:
        client.close()
    if args.json:
        _print_json({
            "profile": creds.profile, "source": creds.source, "key_prefix": creds.key[:12], "api_url": creds.api_url,
            "email": login.get("email"), "key_name": login.get("key_name"), "key_id": login.get("key_id"),
            "account": account,
        })
        return 0
    _print_rows([_signed_in_as(account), *rows])
    return 0


def _print_rows(rows: Iterable[Tuple[str, Optional[str]]]) -> None:
    for label, value in rows:
        if value:
            print(f"{label:<8} {value}")


def cmd_logout(args: argparse.Namespace) -> int:
    config = _read_config()
    login = config.get("profiles", {}).get(args.profile)
    if not login:
        if os.environ.get(API_KEY_ENV):
            _note(f"This shell uses {API_KEY_ENV}, which logout can't clear: unset it.")
        else:
            _note("You're not signed in.")
        return 0
    store = key_store(login["store"])
    key = store.read(args.profile)
    if key:  # revoke it first: a key that can't be revoked stays stored, so you can retry
        client = Client(api_key=key, base_url=login.get("api_url") or DEFAULT_BASE_URL)
        try:
            run_sync(client.request("DELETE", "/v1/keys/current", user=None))
            _note(f"Revoked the key \"{login.get('key_name') or login.get('key_prefix')}\".")
        except Unauthenticated:
            _note("The key was already revoked.")
        finally:
            client.close()
    store.delete(args.profile)
    del config["profiles"][args.profile]
    _write_config(config)
    print("Signed out.")
    return 0


# --- agents and users ----------------------------------------------------------


def cmd_agents_list(args: argparse.Namespace) -> int:
    agents = Agent.list(limit=args.limit, user_filter=ALL_USERS if args.all_users else None)
    if args.json:
        _print_json(agents)
        return 0
    _table(
        ["NAME", "MODEL", "USER", "CREATED", "ID"],
        [(a.name, a.model, a.user_id or "account", a.created_at, a.id) for a in agents],
        empty="No agents yet.",
    )
    return 0


def _lines(prompt: Callable[[], str]) -> Iterator[str]:
    """What you type (after ``prompt()`` at a terminal), or each line piped in."""
    if not sys.stdin.isatty():
        yield from (line.rstrip("\n") for line in sys.stdin)
        return
    while True:
        try:
            yield input(prompt())
        except EOFError:
            print()
            return


def _agent_to_talk_to(name: str) -> Agent:
    """The agent ``name`` the scope can talk to: with ``--user``, that user's own, else the
    account's (which ``Agent.from_name`` never matches inside ``as_user``). An expired one takes no turns."""
    live = [agent for agent in Agent.list(name=name) if agent.status != "expired"]
    found = sorted(live, key=lambda agent: agent.user_id is None)
    if not found:
        raise NotFound(f"No agent is named {name!r}.", next_step="List agents with: noclick agents list")
    return found[0]


def cmd_agents_chat(args: argparse.Namespace) -> int:
    agent = _agent_to_talk_to(args.name)
    conversation = args.conversation
    interactive = args.message is None and sys.stdin.isatty()
    if interactive:
        _note(f"Talking to {args.name}. Ctrl-D or /exit to leave.")
    for text in [args.message] if args.message is not None else _lines(lambda: "you> "):
        if text.strip() in ("/exit", "/quit"):
            break
        if not text.strip():
            continue
        turn = agent.send(text, conversation=conversation)
        try:
            reply = turn.wait()
        except KeyboardInterrupt:
            _note(f"\nThe turn keeps running. Read its reply with: noclick ops wait {turn.id}")
            return 130
        conversation = reply.conversation or conversation
        tools = [call["tool"] for call in reply.tool_calls]
        if tools:
            _note(f"({', '.join(tools)})")
        print(reply.text)
        if interactive:
            print()
    if conversation:
        _note(f"Conversation {conversation}: continue it with --conversation {conversation}")
    return 0


def cmd_users_list(args: argparse.Namespace) -> int:
    users = User.list(q=args.q, status=args.status, limit=args.limit)
    if args.json:
        _print_json(users)
        return 0
    _table(
        ["ID", "NAME", "EMAIL", "STATUS", "CREATED"],
        [(u.id, u.name, u.email, u.status, u.created_at) for u in users],
        empty="No users yet.",
    )
    return 0


def cmd_users_create(args: argparse.Namespace) -> int:
    user = User.create(
        args.id, name=args.name, email=args.email, phone=args.phone,
        spend_cap_usd_per_month=args.spend_cap,
    )
    if args.json:
        _print_json(user)
    else:
        print(user.id)
        _note(f"Created user {user.id}.")
    return 0


def cmd_ops_wait(args: argparse.Namespace) -> int:
    op = Operation.from_id(args.operation_id)
    op.wait(timeout=args.timeout)  # raises the operation's error, or OperationTimeout
    if args.json:
        _print_json(op)
        return 0
    _note(f"{op.kind} {op.status}")
    result = op.result
    if isinstance(result, dict) and isinstance(result.get("text"), str):
        print(result["text"])
    elif result is not None:
        print(json.dumps(result, indent=2, default=str))
    return 0


# --- databases and storage -------------------------------------------------------


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _print_result(result: Any, as_json: bool) -> None:
    if as_json:
        _print_json(result.rows)
        return
    took = f" ({result.duration_ms:.0f} ms)" if result.duration_ms is not None else ""
    if result.columns:
        _table(result.columns, [[row.get(c) for c in result.columns] for row in result.rows], empty="(no rows)")
        _note(f"{_plural(len(result.rows), 'row')}{took}")
    else:
        _note(f"{_plural(result.rows_written, 'row')} written{took}")


def _run_sql(db: Any, sql: str, params: Any, write: bool) -> Any:
    """Reads run read-only; ``--write`` is what lets a statement change data."""
    return db.execute(sql, params) if write else db.query(sql, params)


def cmd_db_query(args: argparse.Namespace) -> int:
    db = Database.from_name(args.database)
    _print_result(_run_sql(db, args.sql, [_value(p) for p in args.param] or None, args.write), args.json)
    return 0


def cmd_db_shell(args: argparse.Namespace) -> int:
    with contextlib.suppress(ImportError):
        import readline  # noqa: F401  (line editing and history for input())
    db = Database.from_name(args.database)
    mode = "reads and writes" if args.write else "read-only"
    _note(f"{args.database}: {db.engine}, {mode}. End each statement with ; and type .help for commands.")
    buffer: List[str] = []
    for line in _lines(lambda: "...> " if buffer else f"{args.database}> "):
        command = line.strip()
        if not buffer and command.startswith("."):
            if command in (".quit", ".exit"):
                break
            _shell_command(db, command)
            continue
        buffer.append(line)
        if not command.endswith(";"):
            continue
        sql, buffer = "\n".join(buffer), []
        try:
            _print_result(_run_sql(db, sql, None, args.write), as_json=False)
        except InvalidRequest as err:  # a SQL error: say so and keep the shell open
            _note(f"error: {err.message}")
    return 0


def _shell_command(db: Any, command: str) -> None:
    name, _, table_name = command.partition(" ")
    if name == ".tables":
        _table(["TABLE", "ROWS"], [(t.name, t.row_count) for t in db.schema()], empty="No tables yet.")
    elif name == ".schema":
        for table in db.schema():
            if table_name.strip() and table.name != table_name.strip():
                continue
            print(f"{table.name}")
            for column in table.columns:
                flags = " primary key" if column.primary_key else (" not null" if not column.nullable else "")
                print(f"  {column.name}  {column.type}{flags}")
    else:
        _note(".tables lists the tables, .schema [table] shows their columns, .quit leaves.")


_REMOTE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]+):(.*)$")


def _remote(path: str) -> Optional[Tuple[str, str]]:
    """``uploads:invoices/0042.pdf`` names a bucket and a key; anything else is a local path."""
    match = _REMOTE.match(path)
    return (match.group(1), match.group(2)) if match else None


def cmd_bucket_ls(args: argparse.Namespace) -> int:
    if args.path is None:
        buckets = Bucket.list()
        if args.json:
            _print_json(buckets)
            return 0
        _table(
            ["NAME", "PUBLIC", "SIZE", "OBJECTS", "CREATED"],
            [(b.name, b.public, _size(b.size_bytes), b.object_count, b.created_at) for b in buckets],
            empty="No buckets yet.",
        )
        return 0
    remote = _remote(args.path)
    name, prefix = remote if remote else (args.path.partition("/")[0], args.path.partition("/")[2])
    # One level at a time, like ls; -r lists every key under the prefix.
    objects = Bucket.from_name(name).objects(prefix=prefix or None, delimiter=None if args.recursive else "/")
    if args.json:
        _print_json(objects)
        return 0
    _table(
        ["SIZE", "UPDATED", "KEY"],
        [(None if o.is_folder else _size(o.size), o.updated_at, o.key) for o in objects],
        empty=f"Nothing in {name}{':' + prefix if prefix else ''}.",
    )
    return 0


def _local_files(root: Path) -> Iterator[Path]:
    return (p for p in sorted(root.rglob("*")) if p.is_file())


def cmd_bucket_cp(args: argparse.Namespace) -> int:
    src, dst = _remote(args.src), _remote(args.dst)
    if bool(src) == bool(dst):
        raise CommandError(
            "Copy between your machine and a bucket: exactly one side is bucket:key.",
            next_step="For example: noclick bucket cp invoice.pdf uploads:invoices/0042.pdf",
        )
    if dst:  # upload
        bucket = Bucket.from_name(dst[0])
        local = Path(args.src)
        if args.src == "-":
            if not dst[1] or dst[1].endswith("/"):
                raise CommandError("Name the key to write stdin to.", next_step="For example: uploads:notes/today.txt")
            pairs = [(dst[1], sys.stdin.buffer.read())]
        elif args.recursive:
            if not local.is_dir():
                raise CommandError(f"{args.src} isn't a folder.", next_step="Drop -r to copy one file.")
            base = dst[1] if not dst[1] or dst[1].endswith("/") else dst[1] + "/"
            pairs = [(base + p.relative_to(local).as_posix(), p) for p in _local_files(local)]
        else:
            pairs = [(dst[1] + local.name if not dst[1] or dst[1].endswith("/") else dst[1], local)]
        for key, source in pairs:
            data = source if isinstance(source, bytes) else source.read_bytes()
            kind = args.content_type or (mimetypes.guess_type(key)[0] if key else None)
            bucket.put(key, data, content_type=kind)
            _note(f"{_size(len(data)):>9}  {dst[0]}:{key}")
        return 0
    bucket = Bucket.from_name(src[0])
    target = Path(args.dst)
    if args.recursive:
        for obj in bucket.objects(prefix=src[1] or None):
            path = target / obj.key[len(src[1]):].lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bucket.read(obj.key))
            _note(f"{_size(obj.size):>9}  {path}")
        return 0
    data = bucket.read(src[1])
    if args.dst == "-":
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return 0
    path = target / src[1].rsplit("/", 1)[-1] if target.is_dir() or args.dst.endswith("/") else target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _note(f"{_size(len(data)):>9}  {path}")
    return 0


# --- apps --------------------------------------------------------------------


def _git(*args: str, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> str:
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise CommandError("git isn't installed.", next_step="Install git, then deploy again.") from None
    if done.returncode:
        raise CommandError(
            done.stderr.strip() or f"git {args[0]} failed.",
            details={"git": list(args), "stderr": done.stderr},
        )
    return done.stdout.strip()


# Git never waits on a prompt nor on a server that sends nothing: it gives up once nothing has moved for this long,
# past the longest NoClick takes to answer itself.
GIT_GIVE_UP_S = 300


def _repo_remote(url: str) -> Dict[str, str]:
    """A one-command git remote for the repo, so the tokened URL never lands in
    argv (other users' ``ps``) or in ``.git/config``."""
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "remote.noclick-deploy.url", "GIT_CONFIG_VALUE_0": url,
            "GIT_TERMINAL_PROMPT": "0", "GIT_HTTP_LOW_SPEED_LIMIT": "1", "GIT_HTTP_LOW_SPEED_TIME": str(GIT_GIVE_UP_S)}


def _push(root: str, url: str, branch: str) -> None:
    env = _repo_remote(url)
    try:
        _git("push", "noclick-deploy", f"HEAD:refs/heads/{branch}", cwd=root, env=env)
    except CommandError as err:
        stderr = err.details.get("stderr") or ""
        if "Operation too slow" in stderr:
            raise CommandError(f"The repo's git endpoint sent nothing for {GIT_GIVE_UP_S} seconds, so the push "
                               "gave up.", next_step="Deploy again.", details=err.details) from None
        if "[rejected]" not in stderr:
            raise
        _git("fetch", "noclick-deploy", f"+refs/heads/{branch}:refs/remotes/noclick/{branch}", cwd=root, env=env)
        raise Conflict(
            f"The repo's {branch} has commits this checkout doesn't (an app service can commit code, too).",
            next_step=f"They're fetched as noclick/{branch}: git merge noclick/{branch}, then deploy again.",
        ) from None


def cmd_deploy(args: argparse.Namespace) -> int:
    try:
        root = _git("rev-parse", "--show-toplevel")
    except CommandError as err:
        if "stderr" not in err.details:  # git itself is missing
            raise
        raise CommandError(
            "This isn't a git checkout.", next_step="Run noclick deploy inside your app's git repository.",
        ) from None
    if _git("status", "--porcelain", "--untracked-files=no", cwd=root):
        raise CommandError(
            "Your checkout has uncommitted changes.",
            next_step="Commit or stash them: deploy ships the commit you're on, never the working tree.",
        )
    branch = args.branch
    if branch is None:
        try:
            branch = _git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=root)
        except CommandError as err:
            if "stderr" not in err.details:
                raise
            raise CommandError("You're not on a branch.", next_step="Pass --branch to name the one to deploy.") from None
    sha = _git("rev-parse", "HEAD", cwd=root)
    if args.app and args.project and args.app != args.project:
        raise CommandError(f"Two apps named: {args.project} and --app {args.app}.", next_step="Name the app once.")
    name = args.app or args.project or Path(root).name
    if args.create:
        repo = Repo.from_name(name, create_if_missing=True)
        budget = UNSET if args.budget is None else args.budget
        project = Project.from_name(name, repo=repo, budget_usd_per_month=budget, create_if_missing=True)
    else:
        project = Project.from_name(name)
        try:
            repo = project.repo
        except NotFound as err:
            if err.details.get("name") != name:  # another NotFound than the name lookup's
                raise
            raise NotFound(
                f"No app is named {name!r}.",
                next_step="Pass --create to create it and its repo with this deploy, or name one: noclick deploy <app>.",
            ) from None
        if args.budget is not None:
            project.update(budget_usd_per_month=args.budget)
    _push(root, repo.clone_url(write=True, ttl_s=600), branch)
    _note(f"Pushed {sha[:7]} to {branch}.")
    op = project.deploy(branch=branch, commit=sha)  # exactly what was pushed, even if the branch moves on
    if args.no_wait:
        print(op.id)
        _note(f"Deploying. Wait for it with: noclick ops wait {op.id}")
        return 0
    _note("Building…")
    try:
        deployment = op.wait()
    except OperationFailed as failed:
        deployment_id = failed.details.get("deployment_id")
        if deployment_id:
            for line in Deployment.from_id(deployment_id).logs(kind="build")[-20:]:
                _note(f"  {line.message}")
        raise
    print(deployment.url)
    _note(f"Ready: {'production' if deployment.production else 'a preview of ' + branch}.")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    project = Project.from_name(args.project)
    since = args.since
    seen: set = set()

    def show() -> Optional[datetime]:
        lines = project.logs(since=since, level=args.level, limit=args.limit)  # oldest first
        for line in lines:
            mark = (line.at, line.deployment_id, line.message)
            if mark in seen:
                continue
            seen.add(mark)
            at = line.at.astimezone().strftime("%H:%M:%S") if isinstance(line.at, datetime) else line.at
            print(f"{at}  {(line.level or '').upper():<5}  {line.message}")
        return lines[-1].at if lines else since

    since = show()
    if not args.follow:
        return 0
    try:
        while True:
            _sleep(POLL_S)
            since = show()
    except KeyboardInterrupt:
        return 0


# --- domains -----------------------------------------------------------------


def cmd_domains_search(args: argparse.Namespace) -> int:
    offers = Domain.search(args.query, tlds=args.tld or None)
    if args.json:
        _print_json(offers)
        return 0
    _table(
        ["DOMAIN", "AVAILABLE", "PRICE", "RENEWAL", "PREMIUM"],
        [(o.name, o.available, _usd(o.price_usd), _usd(o.renewal_usd), o.premium) for o in offers],
        empty=f"No domains found for {args.query}.",
    )
    return 0


def cmd_domains_buy(args: argparse.Namespace) -> int:
    registrant = DomainContact._from(json.loads(Path(args.registrant).read_text())) if args.registrant else None
    if args.user and registrant is None:
        raise InvalidRequest(
            f"A domain for {args.user} is registered to that person, so buying it needs their details.",
            next_step="Pass --registrant with a JSON file of their name, email, phone, address, city, region, "
                      "postal_code, country and agreement_accepted_at (organization is optional).",
            details={"field": "registrant"},
        )
    purchase = Domain.buy(args.name, max_price_usd=args.max_price, years=args.years, registrant=registrant)
    if args.no_wait:
        print(purchase.id)
        _note(f"Buying {args.name}. Wait for it with: noclick ops wait {purchase.id}")
        return 0
    for event in purchase.events(interval=POLL_S):
        if event.status == "awaiting_human":
            _note(f"Waiting for someone to approve the purchase: {purchase.console_url or 'see the console'}")
    domain = purchase.wait()
    print(domain.name)
    _note(f"{domain.name} is yours ({domain.status}), registered until {_cell(domain.expires_at)}.")
    return 0


# --- webhooks and operations -------------------------------------------------


def sign(secret: str, body: bytes, timestamp: int) -> str:
    """The ``NoClick-Signature`` header a delivery carries: HMAC-SHA256 over ``timestamp.body``."""
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _forward(http: httpx.Client, url: str, secret: str, event: Any) -> str:
    body = json.dumps(event.raw, separators=(",", ":")).encode()
    headers = {
        "Content-Type": "application/json", "User-Agent": USER_AGENT,
        SIGNATURE_HEADER: sign(secret, body, int(time.time())),
    }
    try:
        response = http.post(url, content=body, headers=headers)
    except httpx.TransportError as exc:
        return f"failed: {exc.__class__.__name__}"
    return f"{response.status_code} {response.reason_phrase}".rstrip()


def cmd_webhooks_listen(args: argparse.Namespace) -> int:
    secret = args.secret or f"nk_whsec_{secrets.token_hex(24)}"
    kinds = ", ".join(args.events) if args.events else "every event"
    _note(f"Forwarding {kinds} to {args.forward_to}. Ctrl-C stops.")
    _note(f"Signing secret for this session: {secret}  (check it with noclick.Webhook.verify)")
    # Like a webhook with no user: your account's events and every user's, unless --user narrows it.
    users = args.events_user or ALL_USERS
    since = datetime.now(timezone.utc)
    seen: set = set()
    try:
        with httpx.Client(timeout=30) as http:
            while True:
                events = Event.list(type=args.events, since=since, user_filter=users)
                events.sort(key=lambda e: e.created_at)
                for event in events:
                    if event.id in seen:
                        continue
                    outcome = _forward(http, args.forward_to, secret, event)
                    stamp = event.created_at.astimezone().strftime("%H:%M:%S")
                    print(f"{stamp}  {event.type:<28} {event.id}  -> {outcome}")
                if events:  # `since` is inclusive: remember only what sits on the boundary
                    since = events[-1].created_at
                    seen = {e.id for e in events if e.created_at == since}
                _sleep(POLL_S)
    except KeyboardInterrupt:
        return 0


# --- moving a session from this machine ---------------------------------------
# The agent in a coding session moves itself (the guide at noclick.com/move.md): these commands only carry what it
# chose, with the move's own key, kept in a file only you read and never printed.

MOVE_KEY_FILE = "move.json"


def _move_key_path() -> Path:
    return config_dir() / MOVE_KEY_FILE


def _moving() -> AgentMove:
    """The move this machine redeemed, through a client holding the move's own key."""
    path = _move_key_path()
    if not path.exists():
        raise CommandError("No move is under way here.",
                           next_step="Redeem the code your prompt gave: noclick agents move redeem --code nc_move_...")
    saved = json.loads(path.read_text())
    return AgentMove.current(client=Client(api_key=saved["key"], base_url=saved["api_url"]))


def _print_move(move: AgentMove, as_json: bool) -> None:
    if as_json:
        _print_json(move.raw)
        return
    arrived = move.arrived or {}
    print(f"{move.status}: {(move.lands_as or {}).get('name') or ''} -> {(move.lands_as or {}).get('cwd') or ''}")
    for label, value in (("session", (arrived.get("session") or {}).get("messages")), ("repo", (arrived.get("repo") or {}).get("branch")),
                         ("files", len(arrived.get("files") or [])),
                         ("secrets", ", ".join(x["name"] for x in arrived.get("secrets") or [])),
                         ("mcp servers", ", ".join(s["name"] for s in arrived.get("mcp_servers") or [])),
                         ("skills", ", ".join(s["name"] for s in arrived.get("skills") or [])),
                         ("memories", ", ".join(m["name"] for m in arrived.get("memories") or []))):
        if value:
            print(f"  {label:<12} {value}")
    for step in move.steps or []:
        print(f"  step {step['name']:<12} {step['status']}{': ' + step.get('error', '') if step.get('error') else ''}")
    if move.agent_id:
        print(f"  agent {move.agent_id}, conversation {move.conversation}")


def cmd_move_redeem(args: argparse.Namespace) -> int:
    api_url = (args.api_url or os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
    key = AgentMove.redeem(args.code, host=args.host or socket.gethostname(), base_url=api_url)
    _write_private(_move_key_path(), {"key": key, "api_url": api_url})
    _note(f"Redeemed: the move's key is in {_move_key_path()} (only you can read it; it reaches only this move).")
    return 0


def cmd_move_status(args: argparse.Namespace) -> int:
    _print_move(_moving(), args.json)
    return 0


def cmd_move_source(args: argparse.Namespace) -> int:
    move = _moving().set_source(harness=args.harness, host=args.host or socket.gethostname(),
                                cwd=str(Path(args.cwd).resolve()), cli_version=args.cli_version,
                                session_id=args.session_id, title=args.title, model=args.model,
                                effort=args.effort, speed=args.speed)
    _print_move(move, False)
    return 0


def _tar(home: Path, paths: Sequence[str]) -> bytes:
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for rel in paths:
            source = home / rel
            if not source.is_file():
                raise CommandError(f"{source} isn't a file.", next_step="Name the session's own files, relative to "
                                                                        "the harness's home.")
            archive.add(source, arcname=rel)
    return buffer.getvalue()


def cmd_move_session(args: argparse.Namespace) -> int:
    home = Path(os.path.expanduser(args.home)).resolve()
    move = _moving().upload_session(_tar(home, args.files), harness=args.harness, cwd=args.cwd,
                                    session_id=args.session_id)
    session = (move.arrived or {}).get("session") or {}
    print(f"Read {session.get('messages')} messages and {session.get('tool_calls')} tool calls: {session.get('title')}")
    return 0


def _work_commit(root: str, host: str) -> str:
    """HEAD plus every uncommitted and untracked (not ignored) change, as one commit made with a temporary index, so
    your checkout, index and stash never change. HEAD itself when there's nothing uncommitted."""
    import tempfile

    head = _git("rev-parse", "HEAD", cwd=root)
    with tempfile.TemporaryDirectory(prefix="noclick-move-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git("read-tree", "HEAD", cwd=root, env=env)
        _git("add", "-A", cwd=root, env=env)
        tree = _git("write-tree", cwd=root, env=env)
    if tree == _git("rev-parse", "HEAD^{tree}", cwd=root):
        return head
    return _git("commit-tree", tree, "-p", head, "-m", f"Uncommitted work moved from {host}", cwd=root)


def cmd_move_repo(args: argparse.Namespace) -> int:
    try:
        root = _git("rev-parse", "--show-toplevel", cwd=args.path)
    except CommandError as err:
        if "stderr" not in err.details:
            raise
        raise CommandError("This folder isn't a git repository.",
                           next_step="Send its files with noclick agents move file, or make it one (git init, then "
                                     "commit), then run this again.") from None
    host = args.host or socket.gethostname()
    commit = _work_commit(root, host)
    pushed = _moving().repo(name=args.name or Path(root).name, branch=args.branch)
    env = _repo_remote(pushed["url"])
    # The move's own branch: a move run again replaces what its last run pushed.
    _git("push", "noclick-deploy", f"+{commit}:refs/heads/{pushed['branch']}", cwd=root, env=env)
    print(f"Pushed {commit[:7]} to {pushed['name']}, branch {pushed['branch']}: it works in {pushed['cwd']}.")
    return 0


def cmd_move_file(args: argparse.Namespace) -> int:
    source = Path(os.path.expanduser(args.path))
    move = _moving().put_file(args.to or source.name, source.read_bytes())
    print(f"Carried {source} ({_size(source.stat().st_size)}); {len((move.arrived or {}).get('files') or [])} in all.")
    return 0


def _dotenv(path: Path) -> Dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[name.strip()] = value
    return values


def cmd_move_consent(args: argparse.Namespace) -> int:
    """Each secret as name:kind:to, as the person read it, once they said yes in the session; never a value."""
    entries = []
    for given in args.secrets:
        parts = given.split(":", 2)
        if len(parts) != 3 or not all(p.strip() for p in parts):
            raise CommandError(f"'{given}' isn't name:kind:to.", next_step="Like linear-token:Linear API key:env "
                                                                        "LINEAR_API_KEY.")
        entries.append({"name": parts[0].strip(), "kind": parts[1].strip(), "to": parts[2].strip()})
    move = _moving().consent(entries, confirmed=args.yes)
    print(f"The person said yes to: {', '.join(e['name'] for e in move.arrived.get('consent') or [])}")
    return 0


def cmd_move_secret(args: argparse.Namespace) -> int:
    """The value comes from a variable or a file the session reads, never printed."""
    if args.from_env is not None:
        value = os.environ.get(args.from_env)
        if not value:
            raise CommandError(f"{args.from_env} isn't set here.")
    elif args.from_dotenv is not None:
        value = _dotenv(Path(args.dotenv)).get(args.from_dotenv)
        if not value:
            raise CommandError(f"No value for {args.from_dotenv} in {args.dotenv}.")
    else:
        value = Path(os.path.expanduser(args.from_file)).read_text()
    to = ({"env": args.to_env} if args.to_env else {"file": args.to_file, **({"mode": args.mode} if args.mode else {})}
          if args.to_file else {"model": args.to_model} if args.to_model else {})
    _moving().put_secret(args.name, value, to=to)
    print(f"Carried the secret {args.name} (sealed; its value never shown).")
    return 0


def cmd_move_setup(args: argparse.Namespace) -> int:
    _moving().set_setup(list(args.commands))
    print(f"The copy's sandbox runs {len(args.commands)} setup command(s) as it starts.")
    return 0


def cmd_move_checkout(args: argparse.Namespace) -> int:
    move = _moving().set_checkout(args.url, args.branch, path=args.path, secret=args.secret, username=args.username)
    print(f"The copy checks out {args.url} at {args.branch}, in {(move.lands_as or {}).get('cwd') or ''}.")
    return 0


def cmd_move_plan_link(args: argparse.Namespace) -> int:
    link = _moving().plan_link()
    print(link["url"] or f"The {link['integration']} plan is connected already.")
    return 0


def cmd_move_mcp(args: argparse.Namespace) -> int:
    headers = json.loads(Path(args.headers_file).read_text()) if args.headers_file else {}
    if not isinstance(headers, dict) or not all(isinstance(v, (str, dict)) for v in headers.values()):
        raise CommandError("--headers-file holds one JSON object of header names and their values (text, or "
                           '{"secret": name} for a carried secret\'s).')
    _moving().add_mcp_server(args.name, args.url, transport=args.transport, headers=headers)
    print(f"Carried the MCP server {args.name} ({args.url}).")
    return 0


def cmd_move_skill(args: argparse.Namespace) -> int:
    folder = Path(os.path.expanduser(args.folder)).resolve()
    if not (folder / "SKILL.md").is_file():
        raise CommandError(f"{folder} has no SKILL.md.", next_step="Name a skill's own folder.")
    files = [str(p.relative_to(folder)) for p in sorted(folder.rglob("*")) if p.is_file()]
    _moving().add_skill(args.name or folder.name, _tar(folder, files))
    print(f"Carried the skill {args.name or folder.name} ({_plural(len(files), 'file')}).")
    return 0


def _text(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(os.path.expanduser(path)).read_text()


def cmd_move_memory(args: argparse.Namespace) -> int:
    _moving().add_memory(args.name, _text(args.file), description=args.description)
    print(f"Carried the memory {args.name}.")
    return 0


def cmd_move_note(args: argparse.Namespace) -> int:
    _moving().set_note(_text(args.file))
    print("Carried the handoff note.")
    return 0


def cmd_move_instructions(args: argparse.Namespace) -> int:
    _moving().set_instructions(_text(args.file))
    print("Carried its instructions.")
    return 0


def cmd_move_finish(args: argparse.Namespace) -> int:
    move = _moving().finish(name=args.name, model=args.model, model_connection=args.model_connection,
                            harness=args.harness, none=args.none)
    if move.question:  # asked before anything was made: the move's key answers it
        _print_json(move.raw) if args.json else print(move.question)
        return 0
    _move_key_path().unlink(missing_ok=True)
    _print_move(move, args.json)
    return 0


# --- machines ----------------------------------------------------------------

#: A shell's websocket closes with this once its bash has ended (or it sat idle too long).
SHELL_ENDED = 4410


def cmd_machines_ssh(args: argparse.Namespace) -> int:
    machine = Machine.from_name(args.name)
    opened = machine.shell()
    return _attach_shell(opened.url, opened.token)


def _attach_shell(url: str, token: str) -> int:
    """Your terminal on a machine's shell socket, raw, until its bash ends; returns bash's exit code."""
    try:
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect
    except ImportError:
        raise CommandError("A shell needs the command line's extras: pip install 'noclick[cli]'.") from None
    if os.name != "posix" or not sys.stdin.isatty():
        raise CommandError("noclick machines ssh needs a terminal on macOS or Linux (on Windows, use WSL).")
    import shutil
    import signal
    import termios
    import threading
    import tty

    def size() -> Dict[str, int]:
        found = shutil.get_terminal_size((100, 30))
        return {"cols": found.columns, "rows": found.lines}

    ended: Dict[str, Any] = {}
    with connect(url, user_agent_header=USER_AGENT, max_size=None) as socket:
        socket.send(json.dumps({"type": "auth", "token": token, **size()}))
        try:
            json.loads(socket.recv())
        except ConnectionClosed as closed:
            raise CommandError(f"The shell didn't open: {closed.rcvd.reason if closed.rcvd else 'closed'}.") from None
        stdin = sys.stdin.fileno()
        saved = termios.tcgetattr(stdin)

        def typed() -> None:
            while True:
                data = os.read(stdin, 4096)
                if not data:
                    return
                try:
                    socket.send(data)
                except ConnectionClosed:
                    return

        previous = signal.signal(signal.SIGWINCH, lambda *_: socket.send(json.dumps({"type": "resize", **size()})))
        tty.setraw(stdin, termios.TCSANOW)  # what was typed while it connected still goes
        threading.Thread(target=typed, daemon=True).start()
        try:
            for message in socket:
                if isinstance(message, bytes):
                    sys.stdout.buffer.write(message)
                    sys.stdout.buffer.flush()
                elif json.loads(message).get("state") == "exited":
                    ended = json.loads(message)
        except ConnectionClosed:
            pass
        finally:
            termios.tcsetattr(stdin, termios.TCSADRAIN, saved)
            signal.signal(signal.SIGWINCH, previous)
    if ended.get("reason") == "idle":
        _note("\nThe shell closed after sitting idle.")
    elif ended.get("reason") != "exited":
        _note("\nThe connection to the shell was lost.")
    return ended.get("exit_code") or 0


# --- the parser --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noclick",
        description="The NoClick platform from your terminal.",
        epilog="Docs: https://noclick.com/docs/guide/cli",
    )
    parser.add_argument("--version", action="version", version=f"noclick {__version__}")
    parser.add_argument(
        "--profile", default=os.environ.get(PROFILE_ENV, "default"),
        help=f"Which stored login to use (default: {PROFILE_ENV} or 'default').",
    )
    as_json = argparse.ArgumentParser(add_help=False)
    as_json.add_argument("--json", action="store_true", help="Print JSON instead of a table.")
    user = argparse.ArgumentParser(add_help=False)
    user.add_argument("--user", help="Act for this user: your id for them.")
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    def command(
        group: Any, name: str, run: Callable[[argparse.Namespace], int], summary: str, *,
        auth: bool = True, parents: Sequence[argparse.ArgumentParser] = (),
    ) -> argparse.ArgumentParser:
        sub = group.add_parser(name, help=summary, description=summary, parents=list(parents))
        sub.set_defaults(run=run, auth=auth)
        return sub

    def group(name: str, summary: str) -> Any:
        sub = commands.add_parser(name, help=summary, description=summary)
        return sub.add_subparsers(dest="subcommand", metavar="<subcommand>", required=True)

    login = command(commands, "login", cmd_login, "Sign in from a browser and keep the key in your OS keychain.",
                    auth=False)
    login.add_argument("--store", choices=("keychain", "file"), default="keychain",
                       help="Where to keep the key: the OS keychain (default), or a file only you can read.")
    login.add_argument("--no-browser", action="store_true", help="Print the link without opening a browser.")
    command(commands, "whoami", cmd_whoami,
            "Show the account the next command acts in, the key it will use and where that came from.",
            auth=False, parents=[as_json])
    command(commands, "logout", cmd_logout, "Revoke this profile's key and forget it.", auth=False)

    agents = group("agents", "List your agents and talk to them.")
    listing = command(agents, "list", cmd_agents_list, "List agents: yours and the current user's.",
                      parents=[as_json, user])
    listing.add_argument("--all-users", action="store_true", help="Every user's agents, and the account's.")
    listing.add_argument("--limit", type=int, help="Show at most this many.")
    chat = command(agents, "chat", cmd_agents_chat, "Talk to an agent; each line you type is one turn.",
                   parents=[user])
    chat.add_argument("name", help="The agent's name.")
    chat.add_argument("--conversation", help="Continue this conversation (a reply's id, or your own).")
    chat.add_argument("-m", "--message", help="Send one message, print the reply and exit.")

    machines = group("machines", "Reach your machines.")
    ssh = command(machines, "ssh", cmd_machines_ssh,
                  "Open a shell on a machine NoClick runs, in this terminal: no SSH keys or server needed.")
    ssh.add_argument("name", help="The machine's name.")

    move = agents.add_parser("move", help="Carry a coding session from this machine to a NoClick agent.",
                             description="Carry what a coding session chose to a NoClick agent, with the move's own "
                                         "key (the guide: https://noclick.com/move.md).")
    moving = move.add_subparsers(dest="move_command", metavar="<step>", required=True)
    step = command(moving, "redeem", cmd_move_redeem, "Redeem the move code for the move's own key.", auth=False)
    step.add_argument("--code", required=True, help="The code your prompt gave (nc_move_...).")
    step.add_argument("--host", help="This machine's name (default: its hostname).")
    step.add_argument("--api-url", help="The NoClick API, when the prompt names another.")
    command(moving, "status", cmd_move_status, "Where the move lands and what has arrived.", auth=False,
            parents=[as_json])
    step = command(moving, "source", cmd_move_source, "Say where the session moves from.", auth=False)
    step.add_argument("--harness", required=True, choices=("claude_code", "codex", "opencode", "hermes", "openclaw"))
    step.add_argument("--cwd", default=".", help="The folder the session works in (default: here).")
    step.add_argument("--host")
    step.add_argument("--session-id")
    step.add_argument("--cli-version")
    step.add_argument("--title", help="A few words on what the session is about.")
    step.add_argument("--model", help="The model the session runs.")
    step.add_argument("--effort", help="The reasoning effort it runs at, as the harness says it (xhigh).")
    step.add_argument("--speed", help="fast where it runs in its harness's fast mode.")
    step = command(moving, "session", cmd_move_session, "Upload the session's own files.", auth=False)
    step.add_argument("--harness", required=True, choices=("claude_code", "codex", "opencode", "hermes", "openclaw"))
    step.add_argument("--home", required=True, help="The harness's home: ~/.claude, ~/.codex, ~/.local/share ...")
    step.add_argument("--cwd", required=True, help="The folder the session works in, as the harness keys it.")
    step.add_argument("--session-id")
    step.add_argument("files", nargs="+", help="The session's files, relative to --home.")
    step = command(moving, "repo", cmd_move_repo, "Push the code and its uncommitted work to a NoClick repo.",
                   auth=False)
    step.add_argument("--path", default=".", help="A folder in the git repository (default: here).")
    step.add_argument("--name", help="The repo's name (default: the folder's).")
    step.add_argument("--branch", help="The work branch (default: laptop/<host>-<date>).")
    step.add_argument("--host")
    step = command(moving, "file", cmd_move_file, "Carry one file from outside the repo.", auth=False)
    step.add_argument("path", help="The file on this machine.")
    step.add_argument("--to", help="Where it goes under /workspace (default: its name).")
    step = command(moving, "consent", cmd_move_consent, "Record the secrets the person said yes to carrying.",
                   auth=False)
    step.add_argument("secrets", nargs="+", metavar="NAME:KIND:TO", help="Each as the person read it, never a value.")
    step.add_argument("--yes", action="store_true", help="The person said yes in the session.")
    step = command(moving, "secret", cmd_move_secret, "Carry one secret, sealed (its value never printed).",
                   auth=False)
    step.add_argument("name")
    source = step.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-env", metavar="VAR", help="This shell's variable holding it.")
    source.add_argument("--from-dotenv", metavar="VAR", help="A variable in the project's dotenv file (--dotenv).")
    source.add_argument("--from-file", metavar="PATH", help="A file holding it (a CLI's config).")
    step.add_argument("--dotenv", default=".env", help="The dotenv file --from-dotenv reads (default: .env).")
    where = step.add_mutually_exclusive_group()
    where.add_argument("--to-env", metavar="NAME", help="An environment variable in the copy.")
    where.add_argument("--to-file", metavar="PATH", help="A file in the copy (absolute, or under ~/).")
    where.add_argument("--to-model", metavar="PROVIDER", help="The model key the copy runs on (e.g. anthropic).")
    step.add_argument("--mode", help="The file's mode (default: 600).")
    step = command(moving, "setup", cmd_move_setup, "Set what the copy's sandbox runs as it starts.", auth=False)
    step.add_argument("commands", nargs="+", metavar="COMMAND")
    step = command(moving, "checkout", cmd_move_checkout, "Check the session's own git remote out in the copy.",
                   auth=False)
    step.add_argument("--url", required=True, help="The remote's https URL (no login in it).")
    step.add_argument("--branch", required=True, help="The branch the session pushed its work to.")
    step.add_argument("--path", help="Its folder under /workspace (default: the repository's name).")
    step.add_argument("--secret", help="The carried secret that signs the clone in.")
    step.add_argument("--username", help="git's username with that secret (default: x-access-token).")
    command(moving, "plan-link", cmd_move_plan_link, "Print the person's one-tap plan sign-in link.", auth=False)
    step = command(moving, "mcp", cmd_move_mcp, "Carry a remote MCP server.", auth=False)
    step.add_argument("name")
    step.add_argument("--url", required=True, help="Its public https URL.")
    step.add_argument("--transport", choices=("http", "sse"), default="http")
    step.add_argument("--headers-file", metavar="FILE",
                      help='A JSON object of its headers: text, or {"secret": name} for a carried secret\'s.')
    step = command(moving, "skill", cmd_move_skill, "Carry a skill's folder.", auth=False)
    step.add_argument("folder", help="The skill's folder, holding SKILL.md.")
    step.add_argument("--name", help="Its name (default: the folder's).")
    step = command(moving, "memory", cmd_move_memory, "Carry something it learned.", auth=False)
    step.add_argument("name", help="1-64 of a-z 0-9 . _ -.")
    step.add_argument("--file", required=True, help="Its text (Markdown), or - for stdin.")
    step.add_argument("--description", required=True, help="One line on what it's about.")
    step = command(moving, "note", cmd_move_note, "Carry the handoff note.", auth=False)
    step.add_argument("--file", required=True, help="The note (Markdown), or - for stdin.")
    step = command(moving, "instructions", cmd_move_instructions, "Carry its instructions.", auth=False)
    step.add_argument("--file", required=True, help="A user-level CLAUDE.md or AGENTS.md, or - for stdin.")
    step = command(moving, "finish", cmd_move_finish, "Make the agent from what arrived.", auth=False,
                   parents=[as_json])
    step.add_argument("--name")
    step.add_argument("--harness", help="The harness it runs on, when the Draft screen named none.")
    step.add_argument("--none", action="append", choices=["mcp_servers", "skills"],
                      help="What the session has none of, said outright (repeat for both).")
    step.add_argument("--model")
    step.add_argument("--model-connection")

    users = group("users", "List and create users.")
    listing = command(users, "list", cmd_users_list, "List users, newest first.", parents=[as_json])
    listing.add_argument("--q", help="A prefix of the id, name or email.")
    listing.add_argument("--status", choices=("active", "suspended"))
    listing.add_argument("--limit", type=int, help="Show at most this many.")
    create = command(users, "create", cmd_users_create, "Create a user: a person or company your product acts for.",
                     parents=[as_json])
    create.add_argument("id", help="Your own id for the user.")
    create.add_argument("--name")
    create.add_argument("--email")
    create.add_argument("--phone", help="E.164, like +14155550100.")
    create.add_argument("--spend-cap", type=float, metavar="USD", help="Monthly spend cap in dollars.")

    db = group("db", "Query a database.")
    query = command(db, "query", cmd_db_query, "Run one SQL statement and print its rows.",
                    parents=[as_json, user])
    query.add_argument("database", help="The database's name.")
    query.add_argument("sql", help="The statement; use ? for each --param.")
    query.add_argument("-p", "--param", action="append", default=[], metavar="VALUE",
                       help="A value for the next ?, as JSON when it parses (42, null) or else text.")
    query.add_argument("--write", action="store_true", help="Allow a statement that changes data (read-only otherwise).")
    shell = command(db, "shell", cmd_db_shell, "An interactive SQL prompt.", parents=[user])
    shell.add_argument("database", help="The database's name.")
    shell.add_argument("--write", action="store_true", help="Allow statements that change data (read-only otherwise).")

    bucket = group("bucket", "List and copy files in storage buckets.")
    ls = command(bucket, "ls", cmd_bucket_ls, "List buckets, or the files in one.", parents=[as_json, user])
    ls.add_argument("path", nargs="?", metavar="bucket[/prefix]", help="A bucket, optionally with a key prefix.")
    ls.add_argument("-r", "--recursive", action="store_true", help="Every key under the prefix, not one level.")
    cp = command(bucket, "cp", cmd_bucket_cp, "Copy files between your machine and a bucket, written bucket:key.",
                 parents=[user])
    cp.add_argument("src", help="A local path, - for stdin, or bucket:key.")
    cp.add_argument("dst", help="A local path, - for stdout, or bucket:key (a trailing / keeps the file name).")
    cp.add_argument("-r", "--recursive", action="store_true", help="Copy a folder, or every key under a prefix.")
    cp.add_argument("--content-type", metavar="TYPE", help="The upload's content type (guessed from the name otherwise).")

    deploy = command(commands, "deploy", cmd_deploy, "Push the commit you're on and deploy it.",
                     parents=[user])
    deploy.add_argument("project", nargs="?", help="The app to deploy (default: the checkout's folder name).")
    deploy.add_argument("--app", help="The app to deploy, as a flag: the same as the argument.")
    deploy.add_argument("--branch", help="The branch to push and deploy (default: your current one).")
    deploy.add_argument("--create", action="store_true", help="Create the repo and app on the first deploy.")
    deploy.add_argument("--budget", type=float, metavar="USD",
                        help="The app's monthly budget in dollars: what it may spend on hosting, its data, email, AI "
                             "and agents (set, or changed, with this deploy).")
    deploy.add_argument("--no-wait", action="store_true", help="Print the operation id instead of waiting.")
    deploy.add_argument("--token", help="A deploy token, as NoClick's MCP server hands an agent with the command "
                                        "(it reaches one repo and its apps), instead of your key.")
    logs = command(commands, "logs", cmd_logs, "Print an app's logs.", parents=[user])
    logs.add_argument("project", help="The app's name.")
    logs.add_argument("-f", "--follow", action="store_true", help="Keep printing new lines until Ctrl-C.")
    logs.add_argument("--since", type=_since, help="How far back: 15m, 2h, 1d, or an ISO time (default: the latest lines).")
    logs.add_argument("--level", choices=("warn", "error"), help="Only warnings and errors, or only errors.")
    logs.add_argument("--limit", type=int, default=100, help="At most this many lines per read (default 100).")

    domains = group("domains", "Search for and buy domains.")
    search = command(domains, "search", cmd_domains_search, "Check which names are available, and their prices.",
                     parents=[as_json, user])
    search.add_argument("query", help="A name, with or without a TLD.")
    search.add_argument("--tld", action="append", help="Only this TLD (repeat for more).")
    buy = command(domains, "buy", cmd_domains_buy, "Buy a domain, charged to your account, up to a ceiling.",
                  parents=[user])
    buy.add_argument("name", help="The full domain, like acmebooking.com.")
    buy.add_argument("--max-price", type=float, required=True, metavar="USD",
                     help="The most the purchase may cost, in US dollars; a higher price is refused.")
    buy.add_argument("--years", type=int, help="How many years to register it for (the TLD's minimum by default).")
    buy.add_argument("--registrant", metavar="FILE",
                     help="A JSON file of the person it's registered to: name, email, phone, address, city, "
                          "region, postal_code, country, agreement_accepted_at (when they accepted the "
                          "registration agreement), and optionally organization. Required with --user; "
                          "without it your account's default registrant is used.")
    buy.add_argument("--no-wait", action="store_true", help="Print the operation id instead of waiting.")

    webhooks = group("webhooks", "Receive events on your machine.")
    listen = command(webhooks, "listen", cmd_webhooks_listen, "Forward events, signed, to a local URL.")
    listen.add_argument("--forward-to", required=True, metavar="URL", help="Where to POST each event.")
    listen.add_argument("--events", type=lambda s: [t for t in s.split(",") if t],
                        help="Only these event types, comma-separated (patterns like domain.* work).")
    listen.add_argument("--secret", help="Sign with this secret instead of a new one per session.")
    listen.add_argument("--user", dest="events_user",
                        help="Only this user's events (default: your account's and every user's).")

    ops = group("ops", "Wait on operations.")
    wait = command(ops, "wait", cmd_ops_wait, "Wait for an operation to finish and print its result.",
                   parents=[as_json])
    wait.add_argument("operation_id")
    wait.add_argument("--timeout", type=float, metavar="SECONDS", help="Give up after this long (exit 124).")
    return parser


def _report(err: Error) -> None:
    _note(f"error: {err.message}")
    if err.next_step:
        _note(f"  next step: {err.next_step}")
    if err.request_id:
        _note(f"  request id: {err.request_id}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the ``noclick`` command; returns its exit status."""
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "token", None):
            configure(api_key=args.token, base_url=os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL)
        elif args.auth:
            creds = _signed_in(args.profile)
            configure(api_key=creds.key, base_url=creds.api_url)
        scope = as_user(args.user) if getattr(args, "user", None) else contextlib.nullcontext()
        with scope:
            return args.run(args)
    except KeyboardInterrupt:
        _note("")
        return 130
    except Error as err:
        _report(err)
        return 124 if isinstance(err, OperationTimeout) else 1
    except OSError as err:  # a local file the command couldn't read or write
        _note(f"error: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
