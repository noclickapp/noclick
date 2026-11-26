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
from ._sync import run_sync
from ._scope import ALL_USERS, as_user
from ._version import __version__
from .agent import Agent
from .agent_move import AgentMove
from .agent_signup import AgentSignup
from .bucket import Bucket
from .database import Database
from .domain import Domain, DomainContact
from .estimate import Estimate, estimate
from .exceptions import Conflict, Error, InvalidRequest, NotFound, Unauthenticated
from .machine import Machine
from .operation import Operation
from .project import Deployment, Project
from .user import User
from .webhook import SIGNATURE_HEADER, Event
from ._cli import commands as generated, exits, helpscreen, kit as cli_kit, link as cli_link, output, screens
from ._cli import spend as cli_spend, style
from ._cli.output import cell as _cell, note as _note, plain as _plain, plural as _plural, print_json as _print_json
from ._cli.output import size as _size, table as _table, usd as _usd
from ._cli.spec import load as load_spec

PROFILE_ENV = "NOCLICK_PROFILE"
CONFIG_DIR_ENV = "NOCLICK_CONFIG_DIR"
KEYCHAIN_SERVICE = "noclick"
USER_AGENT = f"noclick-cli/{__version__}"

# Polling cadence for `logs --follow` and `webhooks listen`; tests replace _sleep and _clock.
POLL_S = 2.0
_sleep: Callable[[float], None] = time.sleep
_clock: Callable[[], float] = time.monotonic
# The most lines one read of an app's logs answers, which a --grep reads to filter.
MAX_LOG_READ = 1000


class CommandError(Error):
    """A problem the CLI found on your machine (not an API refusal)."""

    type = "command_error"


# --- the command line's own words ----------------------------------------------
# An error's next step and a build log are written for code (``noclick.Database.create(...)``, ``GET /v1/...``): the
# command line says the command that does it instead.

#: What the running command is about, which its words name (the app a deploy or logs reads).
_CONTEXT: Dict[str, str] = {}

_MAKES = {
    "Project": "Create it with its first deploy: noclick deploy {name} --create",
    "Database": "Create it with: noclick db create {name}",
    "Bucket": "Create it with: noclick bucket create {name}",
}
_SDK_MAKES = re.compile(r"(?:Create|Issue|Buy) it with noclick\.(\w+)\.\w+\(.*create_if_missing=True\.?")
_BUILD_LOG_STEP = re.compile(r"Read its build log: GET /v1/deployments/([\w-]+)/logs\?kind=build\.?")
_SETTING_SET = re.compile(r'app\.settings\.set\(("[^"]*"), ("[^"]*")\)')


def _cli_words(text: str) -> str:
    """``text`` with what it says to do in code said as the command that does it."""
    text = _BUILD_LOG_STEP.sub(r"Read its build log: noclick logs --build --deployment \1", text)
    app = _CONTEXT.get("app") or "<app>"
    return _SETTING_SET.sub(lambda m: f"noclick settings set {app} {m.group(1)} {m.group(2)}", text)


def _for_the_terminal(err: Error) -> Tuple[str, Optional[str]]:
    """An error's message and next step as the command line says them."""
    message, step = err.message, err.next_step
    name = err.details.get("name") or ""
    if message.startswith("No project is named"):  # an app, as every other command says
        message = message.replace("No project is named", "No app is named", 1)
    if step:
        made = _SDK_MAKES.search(step)
        if made:
            step = _MAKES.get(made.group(1), "There's no noclick command that makes one: make it in the NoClick app, "
                                             "or in code with noclick.{kind}.create(...).").format(
                name=name or f"<{made.group(1).lower()}>", kind=made.group(1))
        elif step.startswith("Run statements that write with execute"):
            step = "Run it again with --write."
        else:
            step = _cli_words(step)
    return _cli_words(message), step


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
            next_step="pip install keyring, or pass --store file to keep the key in a file only you can read.",
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

    def usable(self) -> bool:
        """Whether the machine has a keychain to keep a key in: a server or container often has none, where the
        keychain library's own backend only refuses."""
        try:
            from keyring.backends import fail
        except ImportError:
            return True
        found = getattr(self._keyring, "get_keyring", None)
        return found is None or not isinstance(found(), fail.Keyring)

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
    """``keychain``, ``file``, or ``auto``: the OS keychain where this machine has one to keep it in, else the file."""
    if name == "file":
        return FileStore()
    if name == "keychain":
        return KeychainStore()
    try:
        store = KeychainStore()
    except CommandError:  # no keychain library
        return FileStore()
    return store if store.usable() else FileStore()


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


# --- what the command line reads -----------------------------------------------


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
    store = key_store(args.store)  # refuse a missing keychain before the browser opens (--store keychain)
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
    keep_key(args.profile, args.store, store, api_url, poll)
    return 0


def keep_key(profile: str, store_name: str, store: Any, api_url: str, got: Dict[str, Any]) -> None:
    """Keep a key ``noclick login`` or ``noclick setup`` got (``got``: its ``key``, ``key_id``, ``key_name`` and the
    account's ``email``) for ``profile``, in ``store`` (with ``auto``, the file when the keychain refuses), and say
    where it went."""
    try:
        store.write(profile, got["key"])
    except CommandError as refused:
        if store_name != "auto":
            raise
        _note(f"{refused.message.rstrip('.')}. Keeping the key in a file only you can read instead.")
        store = FileStore()
        store.write(profile, got["key"])
    config = _read_config()
    config.setdefault("profiles", {})[profile] = {
        "api_url": api_url, "store": store.name, "key_id": got.get("key_id"), "key_name": got.get("key_name"),
        "key_prefix": got["key"][:12], "email": got.get("email"),
        **({"claim_url": got["claim_url"]} if got.get("claim_url") else {}),
    }
    _write_config(config)
    where = "the OS keychain" if store.name == "keychain" else f"{FileStore().path} (only you can read it)"
    said = got["said"] if "said" in got else f"Signed in as {got.get('email') or 'your account'}."
    if said:
        print(said, flush=True)
    _note(f"The key \"{got.get('key_name')}\" is in {where}. noclick logout revokes it.")
    if os.environ.get(API_KEY_ENV):
        _note(f"{API_KEY_ENV} is set in this shell, and wins over the stored key: unset it to use this one.")


def note_unclaimed(profile: str) -> None:
    """On an account ``noclick signup`` made that no person has claimed yet, say so (and where they claim it), once a
    command has signed in; once it's claimed, stop asking."""
    login = _read_config().get("profiles", {}).get(profile, {})
    if "claim_url" not in login or os.environ.get(API_KEY_ENV):
        return
    try:
        status = AgentSignup.current().get("status")
    except Error:
        return
    if status == "unclaimed":
        _note(screens.unclaimed(login["claim_url"]))
    elif status == "claimed":
        config = _read_config()
        config["profiles"][profile].pop("claim_url", None)
        _write_config(config)


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
    note_unclaimed(args.profile)
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
    # One more than shown says whether there are more.
    agents = Agent.list(limit=args.limit + 1 if args.limit else None,
                        user_filter=ALL_USERS if args.all_users else None)
    more = bool(args.limit) and len(agents) > args.limit
    agents = agents[:args.limit] if args.limit else agents
    if args.json:
        _print_json(agents)
        return 0
    _table(
        ["NAME", "MODEL", "USER", "CREATED", "ID"],
        [(a.name, a.model, a.user_id or "account", a.created_at, a.id) for a in agents],
        empty="No agents yet.", title="Agents",
    )
    if more:
        _note(f"The first {args.limit}: there are more (--limit 0 lists every one).")
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
        print(reply.text, flush=True)  # piped, each reply as it comes
        if interactive:
            print()
    if conversation:
        _note(f"Conversation {conversation}: continue it with --conversation {conversation}")
    return 0


def cmd_agents_send(args: argparse.Namespace) -> int:
    """One message, with files, then its reply. ``-`` as the text reads it from stdin, for a text too long to type;
    a long one is never refused: the agent gets what fits and all of it as a file."""
    text = sys.stdin.read() if args.text == "-" else args.text
    if not text.strip():
        raise InvalidRequest("Send some text.", next_step="noclick agents send <agent> 'What changed?'")
    agent = _agent_to_talk_to(args.name)
    turn = agent.send(text, conversation=args.conversation, files=list(args.file or ()))
    if args.no_wait:
        print(turn.id)
        _note(f"Sent. Read its reply with: noclick ops wait {turn.id}")
        return 0
    try:
        reply = turn.wait()
    except KeyboardInterrupt:
        _note(f"\nThe turn keeps running. Read its reply with: noclick ops wait {turn.id}")
        return 130
    if args.json:
        _print_json({"text": reply.text, "conversation": reply.conversation, "tool_calls": reply.tool_calls})
        return 0
    print(reply.text, flush=True)
    if reply.conversation:
        _note(f"Conversation {reply.conversation}: continue it with --conversation {reply.conversation}")
    return 0


def cmd_users_list(args: argparse.Namespace) -> int:
    users = User.list(q=args.q, status=args.status, limit=args.limit)
    if args.json:
        _print_json(users)
        return 0
    _table(
        ["ID", "NAME", "EMAIL", "STATUS", "CREATED"],
        [(u.id, u.name, u.email, u.status, u.created_at) for u in users],
        empty="No users yet.", title="Users",
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
    result = op.result
    if args.json:
        _print_json(op)
    else:
        _note(f"{op.kind} {op.status}")
        if isinstance(result, dict) and isinstance(result.get("text"), str):
            print(result["text"])
        elif result is not None:
            print(json.dumps(result, indent=2, default=str))
    # A deploy or promote that went live but failed its check exits as a failure: the result says what to fix.
    return 1 if op.kind in ("project.deploy", "deployment.promote") and isinstance(result, dict) \
        and _said_deployment(result) else 0


# --- databases and storage -------------------------------------------------------




# A statement that defines the schema: what the engine counts as rows written for it is its own catalog's.
_DEFINES = re.compile(r"^\s*(?:create|drop|alter)\b", re.IGNORECASE)


def _print_result(result: Any, as_json: bool, sql: str = "") -> None:
    if as_json:
        _print_json(result.rows)
        return
    took = f" ({result.duration_ms:.0f} ms)" if result.duration_ms is not None else ""
    if result.columns:
        _table(result.columns, [[row.get(c) for c in result.columns] for row in result.rows], empty="(no rows)")
        _note(f"{_plural(len(result.rows), 'row')}{took}")
    elif _DEFINES.match(sql):
        _note(f"Done{took}.")
    else:
        _note(f"{_plural(result.rows_written, 'row')} written{took}")


def _run_sql(db: Any, sql: str, params: Any, write: bool) -> Any:
    """Reads run read-only; ``--write`` is what lets a statement change data."""
    return db.execute(sql, params) if write else db.query(sql, params)


def cmd_db_query(args: argparse.Namespace) -> int:
    db = Database.from_name(args.database)
    _print_result(_run_sql(db, args.sql, [_value(p) for p in args.param] or None, args.write), args.json, args.sql)
    return 0


def cmd_db_create(args: argparse.Namespace) -> int:
    cli_spend.check([{"kind": "database", "engine": args.engine}], args.max_usd,
                    what=f"A {args.engine} database", per="a month at the usage NoClick assumes")
    db = Database.create(args.name, engine=args.engine, region=args.region)
    print(db.name)
    _note(f"Created the {db.engine} database {db.name}. Query it with: noclick db query {db.name} \"select 1\"")
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
            _print_result(_run_sql(db, sql, None, args.write), as_json=False, sql=sql)
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


# What a folder's copy never uploads: a checkout's own history.
_NOT_UPLOADED = (".git",)


def _local_files(root: Path) -> Iterator[Path]:
    return (p for p in sorted(root.rglob("*"))
            if p.is_file() and not any(part in _NOT_UPLOADED for part in p.relative_to(root).parts))


def cmd_bucket_create(args: argparse.Namespace) -> int:
    cli_spend.check([{"kind": "bucket"}], args.max_usd, what="A bucket", per="a month at the usage NoClick assumes")
    bucket = Bucket.create(args.name, public=args.public, region=args.region)
    print(bucket.name)
    _note(f"Created the {'public ' if args.public else ''}bucket {bucket.name}. Copy a file in with: "
          f"noclick bucket cp <file> {bucket.name}:")
    return 0


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
            if (local / ".git").exists():
                _note(f"Leaving out {local / '.git'}, the checkout's own history.")
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
    try:
        data = bucket.read(src[1])
    except NotFound as missing:
        folder = src[1].rpartition("/")[0]
        raise NotFound(missing.message, next_step=f"List its files with: noclick bucket ls {src[0]}"
                                                  f"{'/' + folder if folder else ''}", details=missing.details) from None
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


def _app(name: str) -> Project:
    """The app ``name``, which the command's words name (``_CONTEXT``)."""
    _CONTEXT["app"] = name
    return Project.from_name(name)


def _said_deployment(result: Dict[str, Any]) -> bool:
    """Say what a deploy's look at its release found (its result as the operation gave it: a deployment read later
    carries none of it); whether its check failed (a ``warning``: it's live but not working)."""
    if result.get("warning"):
        _note(f"warning: {result['warning']}")
        if result.get("next_step"):
            _note(f"  next step: {result['next_step']}")
        return True
    if result.get("code_unchecked"):
        _note(f"note: {result['code_unchecked']}")
    return False


def _build_log(deployment: Deployment, *, last: Optional[int] = None, leave_out: str = "") -> None:
    """A deployment's build log, to stderr (its ``last`` lines), less a last line that only says ``leave_out``: the
    error printed after it."""
    lines = deployment.logs(kind="build")
    if lines and leave_out and lines[-1].message.strip() == leave_out.strip():
        lines = lines[:-1]
    for line in lines[-last:] if last else lines:
        _note(f"  {_cli_words(line.message)}")


def cmd_logs(args: argparse.Namespace) -> int:
    if args.build:
        if args.deployment:
            deployment = Deployment.from_id(args.deployment)
        else:
            if not args.project:
                raise CommandError("Name the app, or a deployment with --deployment.")
            found = _app(args.project).deployments(limit=1)
            if not found:
                raise NotFound(f"{args.project} has no deployments yet.",
                               next_step=f"Deploy it with: noclick deploy {args.project}")
            deployment = found[0]
        _note(f"Build log of {deployment.id} ({deployment.branch}, {(deployment.commit or '')[:7]}, {deployment.status}):")
        for line in deployment.logs(kind="build"):
            print(f"{(line.level or '').upper():<5}  {_cli_words(line.message)}", flush=True)
        return 0
    project = _app(cli_link.app_name(args.project))
    since = args.since
    seen: set = set()
    grep = args.grep.lower() if args.grep else None
    # Filtered here, so a read with --grep reads the most the API answers and shows at most --limit of what matches.
    read_limit = MAX_LOG_READ if grep else args.limit
    ends = None if args.timeout is None else _clock() + args.timeout

    def show() -> Tuple[Optional[datetime], int, int]:
        lines = project.logs(since=since, level=args.level, limit=read_limit)  # oldest first
        fresh, new = [], 0
        for line in lines:
            mark = (line.at, line.deployment_id, line.message)
            if mark in seen:
                continue
            seen.add(mark)
            new += 1
            if grep is None or grep in (line.message or "").lower():
                fresh.append(line)
        # The latest of them when it's the first read of the latest lines, else the first after since.
        shown = fresh[-args.limit:] if since is None else fresh[:args.limit]
        for line in shown:
            # Flushed: piped (| grep, > file), each line as it comes, and none lost to Ctrl-C.
            if args.json:
                output.line(json.dumps({"at": line.at.isoformat() if isinstance(line.at, datetime) else line.at,
                                     "level": line.level, "message": line.message,
                                     "deployment_id": line.deployment_id, **{k: line.raw.get(k) for k in (
                                         "environment", "request_id", "status") if line.raw.get(k) is not None}}))
            else:
                at = line.at.astimezone().strftime("%H:%M:%S") if isinstance(line.at, datetime) else line.at
                output.line(f"{at}  {(line.level or '').upper():<5}  {line.message}")
        if not args.follow:
            if len(fresh) > len(shown):
                _note(f"Showing {len(shown)} of {len(fresh)} lines{' that match' if grep else ''}: raise --limit, or "
                      "narrow it with --since, --level or --grep.")
            elif len(lines) >= read_limit:
                _note(f"Showing the {'first' if since else 'last'} {len(shown)} lines read: there may be more "
                      f"({'a later --since' if since else '--since'} reads {'on' if since else 'further back'}).")
            elif not lines and lines.delay_s:
                _note(f"No lines{' since then' if since else ''}. A line takes up to {lines.delay_s}s to show after "
                      "its request: read again in a moment, or follow them with -f.")
            elif lines and not shown:
                _note(f"No lines match {args.grep!r}.")
        return (lines[-1].at if lines else since), new, len(shown)

    since, read, _ = show()
    if not args.follow:
        return 0
    try:
        while ends is None or _clock() < ends:
            if read < read_limit:  # a read full of new lines may have stopped short of the newest: read on at once
                _sleep(POLL_S)
            since, read, _ = show()
    except KeyboardInterrupt:
        return 0
    return 0


# --- settings ----------------------------------------------------------------


def cmd_settings_list(args: argparse.Namespace) -> int:
    found = _app(args.project).settings.list()
    if args.json:
        _print_json(found)
        return 0
    _table(["NAME", "VALUE"], sorted(found.items()), empty=f"{args.project} has no settings.",
           title=f"Settings of {args.project}")
    return 0


def cmd_settings_set(args: argparse.Namespace) -> int:
    _app(args.project).settings.set(args.name, args.value)
    _note(f"Set {args.name}. It reaches {args.project} at its next deploy: noclick deploy {args.project}")
    return 0


def cmd_settings_delete(args: argparse.Namespace) -> int:
    _app(args.project).settings.delete(args.name)
    _note(f"Deleted {args.name}. {args.project} stops seeing it at its next deploy.")
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
        empty=f"No domains found for {args.query}.", title=f"Domains for {args.query}",
    )
    asked = args.query.strip().lower().rstrip(".")
    if "." in asked and all(o.name.lower() != asked for o in offers):
        _note(f"{asked} isn't for sale here: it's registered, or it names a well-known brand or bank, which NoClick "
              "never offers.")
    return 0


def cmd_domains_buy(args: argparse.Namespace) -> int:
    # Left out, the registrant on file is used: the account's default, or with --user that user's registrant profile.
    registrant = DomainContact._from(json.loads(Path(args.registrant).read_text())) if args.registrant else None
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


# --- estimates ---------------------------------------------------------------


def _estimate_items(path: str) -> List[Dict[str, Any]]:
    """The items in ``path`` (``-``: stdin): a JSON list of them, or an object holding them under ``items``."""
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise CommandError(f"{path} isn't JSON: {exc}.",
                           next_step='Write a list of items, like [{"kind": "project", "usage": {"requests": 100000}}].')
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise CommandError(f"{path} holds no list of items.",
                           next_step='Write a list of items, or {"items": [...]}.')
    return items


def _pairs(given: Sequence[str], *, number: bool = False) -> Dict[str, Any]:
    """``NAME=VALUE`` from the command line, each value a number when ``number``."""
    found: Dict[str, Any] = {}
    for pair in given:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            raise CommandError(f"{pair!r} isn't NAME=VALUE.", next_step="Like --usage hours=40")
        try:
            found[name] = float(value) if number else value
        except ValueError:
            raise CommandError(f"{name}'s usage is a number, not {value!r}.") from None
    return found


def _options(options: Dict[str, Any]) -> str:
    """What a kind's variant is priced as, in a few words: its plain options (a runtime, a region, an engine); the
    rest, such as a size's every field, only in --json."""
    return ", ".join(str(v) for v in options.values() if v and isinstance(v, (str, int, float)))


def cmd_estimate(args: argparse.Namespace) -> int:
    if args.kinds:
        kinds = Estimate.kinds(region=args.region)
        if args.json:
            _print_json(kinds)
            return 0
        _table(["KIND", "AS", "CHARGE", "UNIT PRICE", "PER", "USAGE (DEFAULT)"],
               [(k.kind, _options(k.options), p.charge, f"${p.unit_usd:g}", p.unit,
                 ", ".join(f"{u.name} ({u.default:g})" for u in k.usage if u.name in p.usage_fields))
                for k in kinds for p in k.prices], empty="Nothing to estimate.")
        return 0
    if not args.file:
        raise CommandError("Name what to estimate: a kind (noclick estimate database), or a JSON file of items (- for "
                           "stdin).", next_step="Run noclick estimate --kinds to see what each kind takes.")
    if args.file != "-" and not Path(args.file).exists() and re.fullmatch(r"[a-z_]+", args.file):
        # One item by its kind, its usage and options from the command line.
        # Its options sit beside its kind, as the API takes them (runtime, engine, region, framework).
        items = [{**_pairs(args.option), "kind": args.file,
                  **({"usage": _pairs(args.usage, number=True)} if args.usage else {})}]
    else:
        items = _estimate_items(args.file)
    est = estimate(items)
    if args.json:
        _print_json(est)
        return 0
    _table(["ITEM", "CHARGE", "QUANTITY", "UNIT", "UNIT PRICE", "A MONTH"],
           [(line.item or line.kind, line.charge + (" *" if line.assumed else ""), f"{line.quantity:g}", line.unit,
             f"${line.unit_usd:g}", f"${line.usd:,.4f}") for line in est.lines], empty="Nothing was priced.")
    print(f"Total: {_usd(est.monthly_usd)} a month")
    for item in est.items:
        if item.assumed:
            _note(f"Assumed ({item.name or item.kind}): {', '.join(item.assumed)}")
    if any(line.assumed for line in est.lines):
        _note("* a default decided it: give that usage or option to price it as you expect.")
    for item in est.items:
        for left_out in item.not_included:
            _note(f"Not included ({item.name or item.kind}): {left_out}")
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
                    print(f"{stamp}  {event.type:<28} {event.id}  -> {outcome}", flush=True)
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
    return _attach_shell(opened.url, opened.token, renew=lambda: machine.shell().token)


def _attach_shell(url: str, token: str, *, renew: Callable[[], str]) -> int:
    """Your terminal on a machine's shell socket, raw, until its bash ends; returns bash's exit code. It says it
    renews, so the shell lasts 15 minutes at a time: when the server asks, ``renew`` gets a new token for it, and bash
    goes on."""
    try:
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect
    except ImportError:
        raise CommandError("A shell needs websockets: pip install websockets.") from None
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
        socket.send(json.dumps({"type": "auth", "token": token, "renew": True, **size()}))
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

        def renewed() -> None:
            try:
                socket.send(json.dumps({"type": "renew", "token": renew()}))
            except (Error, ConnectionClosed):
                return  # unrenewed, it closes at its time

        previous = signal.signal(signal.SIGWINCH, lambda *_: socket.send(json.dumps({"type": "resize", **size()})))
        tty.setraw(stdin, termios.TCSANOW)  # what was typed while it connected still goes
        threading.Thread(target=typed, daemon=True).start()
        try:
            for message in socket:
                if isinstance(message, bytes):
                    sys.stdout.buffer.write(message)
                    sys.stdout.buffer.flush()
                    continue
                said = json.loads(message)
                if said.get("type") == "renew":
                    threading.Thread(target=renewed, daemon=True).start()
                elif said.get("state") == "exited":
                    ended = said
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


def _curated(path: Sequence[str]) -> bool:
    """Whether ``path`` is a curated command, or a group of them."""
    return any(c["path"][:len(path)] == list(path) for c in load_spec().commands)


class _Parser(argparse.ArgumentParser):
    """A command's parser: its help ends with the command's examples, as the manifest keeps them."""

    def _check_value(self, action: argparse.Action, value: Any) -> None:
        # A command it doesn't have: the closest ones it does, rather than every one.
        if isinstance(action, argparse._SubParsersAction) and value not in action.choices:
            within = self.prog.split()[1:]
            curated = [n for n in action.choices if _curated([*within, n])]
            self.exit(exits.USAGE, screens.unknown(
                value, within=within, curated=curated, areas=[n for n in action.choices if n not in curated],
                s=style.ERR) + "\n")
        super()._check_value(action, value)

    def format_help(self) -> str:
        path = self.prog.split()[1:]
        found = next((c.get("examples") for c in load_spec().commands if c["path"] == path), None)
        if style.OUT.on:
            return helpscreen.screen(self, style.OUT, examples=found or ())
        text = super().format_help()
        return f"{text}\n{screens.examples(found)}\n" if found else text


class _Top(_Parser):
    """``noclick`` itself: its help lists the curated commands by section and the API's areas as one line, or
    each of them with ``--all``."""

    show_all = False

    def format_help(self) -> str:
        sub = next(a for a in self._actions if isinstance(a, argparse._SubParsersAction))
        summaries = {a.dest: a.help or "" for a in sub._choices_actions if _curated([a.dest])}
        areas = {a: len(ops) for a, ops in load_spec().areas().items()} if self.show_all else None
        if style.OUT.on:
            return helpscreen.screen(self, style.OUT, middle=screens.commands(summaries, areas, style.OUT).split("\n"))
        head = self._get_formatter()
        head.add_usage(self.usage, self._actions, self._mutually_exclusive_groups)
        head.add_text(self.description)
        tail = self._get_formatter()
        tail.start_section("options")
        tail.add_arguments([a for a in self._actions if a.option_strings and a.help != argparse.SUPPRESS])
        tail.end_section()
        tail.add_text(self.epilog)
        return f"{head.format_help()}\n{screens.commands(summaries, areas)}\n\n{tail.format_help()}"


def build_parser(argv: Sequence[str] = (), *, areas: bool = True) -> argparse.ArgumentParser:
    """The parser; an area of the API's operations named in ``argv`` gets its commands (``_cli.commands``), and
    ``areas=False`` leaves them all out (the curated commands alone, as the manifest lists them)."""
    parser = _Top(
        prog="noclick",
        description="The NoClick platform from your terminal.",
        epilog="Exit status: 0 done, 1 failed, 2 the command line was wrong, 3 waiting on a person (a link says where), "
               "4 refused by a limit, a price or a policy, 124 a wait ran out, 130 Ctrl-C. "
               "Docs: https://noclick.com/docs/guide/cli",
    )
    parser.add_argument("--version", action="version", version=f"noclick {__version__}")
    parser.add_argument(
        "--profile", default=os.environ.get(PROFILE_ENV, "default"),
        help=f"Which stored login to use (default: {PROFILE_ENV} or 'default').",
    )
    parser.add_argument("--color", choices=style.MODES, default="auto",
                        help="Colours and tables: auto (only at a terminal, never under NO_COLOR, TERM=dumb or CI), "
                             "always or never.")
    parser.add_argument("--all", action="store_true", help=argparse.SUPPRESS)  # with --help: every API area
    parser.show_all = "--all" in argv
    as_json = argparse.ArgumentParser(add_help=False)
    as_json.add_argument("--json", action="store_true", help="Print JSON instead of a table.")
    user = argparse.ArgumentParser(add_help=False)
    user.add_argument("--user", help="Act for this user: your id for them.")
    commands = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)

    def command(
        group: Any, name: str, run: Callable[[argparse.Namespace], int], summary: str, *,
        auth: bool = True, parents: Sequence[argparse.ArgumentParser] = (),
    ) -> argparse.ArgumentParser:
        sub = group.add_parser(name, help=summary, description=summary, parents=list(parents))
        sub.set_defaults(run=run, auth=auth)
        return sub

    groups: Dict[str, Any] = {}

    def group(name: str, summary: str) -> Any:
        sub = commands.add_parser(name, help=summary, description=summary)
        groups[name] = sub.add_subparsers(dest="subcommand", metavar="<subcommand>", required=True)
        return groups[name]

    login = command(commands, "login", cmd_login, "Sign in from a browser and keep the key in your OS keychain "
                                                  "(or a file only you can read where there's none).",
                    auth=False)
    login.add_argument("--store", choices=("auto", "keychain", "file"), default="auto",
                       help="Where to keep the key: the OS keychain, or a file only you can read (default: the "
                            "keychain where this machine has one, else the file).")
    login.add_argument("--no-browser", action="store_true", help="Print the link without opening a browser.")
    command(commands, "whoami", cmd_whoami,
            "Show the account the next command acts in, the key it will use and where that came from.",
            auth=False, parents=[as_json])
    command(commands, "logout", cmd_logout, "Revoke this profile's key and forget it.", auth=False)

    agents = group("agents", "List your agents and talk to them.")
    listing = command(agents, "list", cmd_agents_list, "List agents: yours and the current user's.",
                      parents=[as_json, user])
    listing.add_argument("--all-users", action="store_true", help="Every user's agents, and the account's.")
    listing.add_argument("--limit", type=int, default=50, help="Show at most this many (default 50; 0 for all).")
    chat = command(agents, "chat", cmd_agents_chat, "Talk to an agent; each line you type is one turn.",
                   parents=[user])
    chat.add_argument("name", help="The agent's name.")
    chat.add_argument("--conversation", help="Continue this conversation (a reply's id, or your own).")
    chat.add_argument("-m", "--message", help="Send one message, print the reply and exit.")
    send = command(agents, "send", cmd_agents_send, "Send an agent one message, with files, and print its reply.",
                   parents=[as_json, user])
    send.add_argument("name", help="The agent's name.")
    send.add_argument("text", help="The message, or - to read it from stdin. A long one is never refused: the "
                                   "agent gets what fits, and all of it as a file.")
    send.add_argument("--file", action="append", metavar="PATH",
                      help="A file to send with it (repeat for several); it lands in the agent's workspace too.")
    send.add_argument("--conversation", help="The conversation it goes in (a reply's id, or your own).")
    send.add_argument("--no-wait", action="store_true", help="Print the turn's operation id instead of its reply.")

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
    made = command(db, "create", cmd_db_create, "Create a database.", parents=[user])
    made.add_argument("name", help="Its name: 1-64 letters, digits and . _ -.")
    made.add_argument("--engine", choices=("sqlite", "postgres"), default="sqlite", help="Default: sqlite.")
    made.add_argument("--region", help="Where its data is kept, for good (default: your account's default region).")
    cli_spend.add_flag(made, what="it (a month, at the usage NoClick assumes)")
    shell = command(db, "shell", cmd_db_shell, "An interactive SQL prompt.", parents=[user])
    shell.add_argument("database", help="The database's name.")
    shell.add_argument("--write", action="store_true", help="Allow statements that change data (read-only otherwise).")

    bucket = group("bucket", "List and copy files in storage buckets.")
    ls = command(bucket, "ls", cmd_bucket_ls, "List buckets, or the files in one.", parents=[as_json, user])
    ls.add_argument("path", nargs="?", metavar="bucket[/prefix]", help="A bucket, optionally with a key prefix.")
    ls.add_argument("-r", "--recursive", action="store_true", help="Every key under the prefix, not one level.")
    mb = command(bucket, "create", cmd_bucket_create, "Create a bucket.", parents=[user])
    mb.add_argument("name", help="Its name: 1-64 letters, digits and . _ -.")
    mb.add_argument("--public", action="store_true", help="Serve every file at a plain URL.")
    mb.add_argument("--region", help="Where its files are kept (default: your account's default region).")
    cli_spend.add_flag(mb, what="it (a month, at the usage NoClick assumes)")
    cp = command(bucket, "cp", cmd_bucket_cp, "Copy files between your machine and a bucket, written bucket:key.",
                 parents=[user])
    cp.add_argument("src", help="A local path, - for stdin, or bucket:key.")
    cp.add_argument("dst", help="A local path, - for stdout, or bucket:key (a trailing / keeps the file name).")
    cp.add_argument("-r", "--recursive", action="store_true",
                    help="Copy a folder (never its .git), or every key under a prefix.")
    cp.add_argument("--content-type", metavar="TYPE", help="The upload's content type (guessed from the name otherwise).")

    logs = command(commands, "logs", cmd_logs, "Print an app's logs, or a deployment's build log.", parents=[user])
    logs.add_argument("project", nargs="?", help="The app's name.")
    logs.add_argument("--build", action="store_true", help="Print a build log: the app's newest deployment's, or "
                                                          "--deployment's.")
    logs.add_argument("--deployment", metavar="ID", help="With --build: this deployment's build log.")
    logs.add_argument("-f", "--follow", action="store_true", help="Keep printing new lines until Ctrl-C (or --timeout).")
    logs.add_argument("--since", type=_since, help="How far back: 15m, 2h, 1d, or an ISO time (default: the latest lines).")
    logs.add_argument("--level", choices=("warn", "error"), help="Only warnings and errors, or only errors.")
    logs.add_argument("--grep", metavar="TEXT", help="Only lines holding this text (any case).")
    logs.add_argument("--limit", type=int, default=100, help="At most this many lines per read (default 100).")
    logs.add_argument("--timeout", type=float, metavar="SECONDS", help="With -f: stop following after this long.")
    logs.add_argument("--json", action="store_true", help="One JSON object a line: at, level, message, deployment_id, "
                                                          "environment, request_id, status.")

    settings = group("settings", "An app's plain settings, which it reads from its environment.")
    listed = command(settings, "list", cmd_settings_list, "List an app's settings and their values.",
                     parents=[as_json, user])
    listed.add_argument("project", help="The app's name.")
    setting = command(settings, "set", cmd_settings_set, "Set one (it reaches the app at its next deploy).",
                      parents=[user])
    setting.add_argument("project", help="The app's name.")
    setting.add_argument("name", help="Letters, digits and _, starting with a letter.")
    setting.add_argument("value", help="At most 4 KB; put anything sensitive in the app's secrets instead.")
    unset = command(settings, "delete", cmd_settings_delete, "Delete one (from the app's next deploy).",
                    parents=[user])
    unset.add_argument("project", help="The app's name.")
    unset.add_argument("name")

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
                          "registration agreement), and optionally organization. Without it the registrant on "
                          "file is used: your account's default, or with --user that user's registrant profile.")
    buy.add_argument("--no-wait", action="store_true", help="Print the operation id instead of waiting.")

    priced = command(commands, "estimate", cmd_estimate,
                     "What apps, databases, buckets and repos would cost a month, before you make them.",
                     parents=[as_json, user])
    priced.add_argument("file", nargs="?", metavar="KIND|FILE",
                        help='A kind (database, live_editing, ... from --kinds), or a JSON file of items (- for '
                             'stdin), like [{"kind": "project", "usage": {"requests": 100000}}, {"kind": "database"}].')
    priced.add_argument("--usage", action="append", default=[], metavar="NAME=N",
                        help="With a kind: its usage a month, like requests=100000 (repeat for more).")
    priced.add_argument("--option", action="append", default=[], metavar="NAME=VALUE",
                        help="With a kind: one of its options, like runtime=container (repeat for more).")
    priced.add_argument("--kinds", action="store_true",
                        help="List what can be estimated: each kind's charges, unit prices and usage defaults.")
    priced.add_argument("--region", help="With --kinds: price a container app in this region.")

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
    wait.epilog = "A deploy or promote that went live but failed its check (its result's warning) exits 1."
    wait.add_argument("operation_id")
    wait.add_argument("--timeout", type=float, metavar="SECONDS", help="Give up after this long (exit 124).")

    # The parts (noclick._cli.parts), each adding its own commands, then the built-ins and the generated ones,
    # which never take a name a command above has.
    built = cli_kit.Kit(commands=commands, command=command, group=group, as_json=as_json, user=user, groups=groups)
    for part in cli_kit.parts():
        part.register(built)
    generated.add_builtins(commands, [as_json])
    if areas:
        generated.add_areas(commands, [as_json, user], argv)
    return parser


def _first_screen(profile: str) -> int:
    """``noclick`` alone: what it is and what to run first; signed in, who you are and the folder's app."""
    login = _read_config().get("profiles", {}).get(profile, {})
    said = screens.signed_in(login.get("email") if login.get("store") else None,
                             from_env=API_KEY_ENV if os.environ.get(API_KEY_ENV) else None)
    try:
        linked = cli_link.find()
    except Error:
        linked = None
    print(screens.first(signed_in=said, linked_app=linked.app if linked and said else None, s=style.OUT))
    return exits.OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the ``noclick`` command; returns its exit status."""
    argv = list(sys.argv[1:] if argv is None else argv)
    style.configure(style.mode_in(argv))
    args = build_parser(argv).parse_args(argv)
    if args.command is None:
        return _first_screen(args.profile)
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
        return exits.INTERRUPTED
    except BrokenPipeError:  # the reader (`| head`) stopped reading: nothing more to say, to anyone
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return exits.OK
    except Error as err:
        return output.report(err, as_json=getattr(args, "json", False), said=_for_the_terminal(err),
                             commands=generated.commands_for(load_spec()))
    except OSError as err:  # a local file the command couldn't read or write
        return output.report(CommandError(str(err)), as_json=getattr(args, "json", False))


if __name__ == "__main__":
    sys.exit(main())
