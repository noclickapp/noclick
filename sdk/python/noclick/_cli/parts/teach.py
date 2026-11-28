"""Teach: ``noclick docs`` and ``noclick skill`` print the guides and skills as Markdown for an agent's context (no
key needed), and ``noclick mcp`` sets NoClick's MCP server up in a coding agent's harness (``noclick help --json``
lists every command: the shared surface's)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..._client import API_KEY_ENV
from ...docs import Docs
from ...exceptions import NotFound
from .. import output as out

MCP_URL_ENV = "NOCLICK_MCP_URL"
DEFAULT_MCP_URL = "https://mcp.noclick.com"
SERVER = "noclick"


# --- docs and skills ----------------------------------------------------------


def _print_doc(doc_id: str) -> int:
    try:
        doc = Docs.read(doc_id)
    except NotFound:
        hits = Docs.search(doc_id.split(":", 1)[-1].replace("-", " "), limit=5)
        read = [f"noclick docs {h.id}" for h in hits] or ["noclick docs"]
        raise out.run(NotFound(f"No doc is called {doc_id!r}.",
                               next_step=f"Read one of these: {', '.join(read)}" if hits else "List them with: noclick docs"),
                      read) from None
    out.line(f"# {doc.title}\n\n{doc.text.strip()}")
    if doc.sections:
        out.note(f"Its sections, one at a time: noclick docs {doc.sections[0]} ({len(doc.sections)} in all: "
                 f"{', '.join(doc.sections[:6])}{', …' if len(doc.sections) > 6 else ''})")
    if doc.url:
        out.note(f"On the web: {doc.url}")
    return 0


def _print_hits(hits: List[Any], as_json: bool, *, empty: str, how: str) -> int:
    if as_json:
        out.print_json(hits)
        return 0
    out.table(["ID", "TITLE", "ABOUT"], [(h.id, h.title, h.snippet[:90]) for h in hits], empty=empty)
    if hits:
        out.note(how)
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    if args.search:
        return _print_hits(Docs.search(args.search, kind=args.kind, limit=args.limit), args.json,
                           empty=f"Nothing found for {args.search!r}.", how="Read one with: noclick docs <id>")
    if args.topic:
        return _print_doc(args.topic)
    return _print_hits(Docs.search(kind=args.kind or "guide"), args.json, empty="No guides.",
                       how="Read one with: noclick docs <id> (or its name: noclick docs apps). Search them with "
                           "noclick docs --search <words>; the task playbooks are noclick skill.")


def cmd_skill(args: argparse.Namespace) -> int:
    if args.name:
        return _print_doc(args.name if ":" in args.name else f"skill:{args.name}")
    return _print_hits(Docs.search(kind="skill"), args.json, empty="No skills.",
                       how="Read one with: noclick skill <name> (its id without skill:).")


# --- MCP ---------------------------------------------------------------------


def _mcp_url() -> str:
    return os.environ.get(MCP_URL_ENV) or DEFAULT_MCP_URL


def _merge_json(path: Path, key: str, entry: Dict[str, Any]) -> bool:
    """Add ``entry`` as ``SERVER`` under ``key`` in the JSON file at ``path``; False when it holds one already."""
    data = json.loads(path.read_text()) if path.is_file() and path.read_text().strip() else {}
    servers = data.setdefault(key, {})
    if SERVER in servers:
        return False
    servers[SERVER] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def _codex(path: Path, url: str, key_env: Optional[str]) -> str:
    lines = [f"[mcp_servers.{SERVER}]", f'url = "{url}"']
    if key_env:
        lines.append(f'bearer_token_env_var = "{key_env}"')
    return "\n".join(lines) + "\n"


def cmd_mcp(args: argparse.Namespace) -> int:
    url = _mcp_url()
    key_env = None if args.oauth else args.key_env
    harness = args.harness
    if harness == "claude":
        entry: Dict[str, Any] = {"type": "http", "url": url,
                                 **({"headers": {"Authorization": f"Bearer ${{{key_env}}}"}} if key_env else {})}
        path, key, text = Path(args.dir) / ".mcp.json", "mcpServers", None
    elif harness == "cursor":
        entry = {"url": url, **({"headers": {"Authorization": f"Bearer ${{env:{key_env}}}"}} if key_env else {})}
        path, key, text = Path(args.dir) / ".cursor" / "mcp.json", "mcpServers", None
    elif harness == "codex":
        path = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
        entry, key, text = {}, "", _codex(path, url, key_env)
    else:
        out.print_json({"url": url, "auth": "oauth" if not key_env else {"header": "Authorization",
                                                                        "value": f"Bearer ${key_env}"}})
        return 0
    shown = text if text is not None else json.dumps({key: {SERVER: entry}}, indent=2) + "\n"
    if not args.install:
        out.line(shown.rstrip())
        out.note(f"That's {path}'s entry for NoClick. Pass --install to add it there.")
    elif text is not None:
        held = path.read_text() if path.is_file() else ""
        if f"[mcp_servers.{SERVER}]" in held:
            out.note(f"{path} has a {SERVER} server already: nothing changed.")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(held + ("\n" if held and not held.endswith("\n\n") else "") + text)
            out.note(f"Added NoClick to {path}.")
    elif _merge_json(path, key, entry):
        out.note(f"Added NoClick to {path}.")
    else:
        out.note(f"{path} has a {SERVER} server already: nothing changed.")
    if key_env:
        set_here = bool(os.environ.get(key_env))
        out.note(f"It signs in with the key in {key_env} as the harness starts (the file names the variable, never "
                 f"the key){'' if set_here else f': set {key_env} where the harness runs (noclick setup or login keeps it for this CLI only)'}.")
    else:
        out.note("The harness signs in to NoClick in a browser the first time it connects.")
    out.note("Restart the harness (or start a new session) to load it.")
    return 0


def register(kit: Any) -> None:
    docs = kit.command(kit.commands, "docs", cmd_docs,
                       "Print a guide as Markdown (no key needed), list them, or search every doc.",
                       auth=False, parents=[kit.as_json])
    docs.add_argument("topic", nargs="?", help="A doc's id or a guide's name (apps, databases, cli...).")
    docs.add_argument("--search", metavar="WORDS", help="Search the guides, skills, reference and API.")
    docs.add_argument("--kind", choices=("guide", "skill", "reference", "example", "event", "api"),
                      help="Only this kind of doc.")
    docs.add_argument("--limit", type=int, default=10, help="With --search: at most this many (default 10).")
    skill = kit.command(kit.commands, "skill", cmd_skill,
                        "Print a skill, a task's playbook, as Markdown (no key needed), or list them.",
                        auth=False, parents=[kit.as_json])
    skill.add_argument("name", nargs="?", help="The skill's name, like ship-an-app.")
    mcp = kit.command(kit.commands, "mcp", cmd_mcp,
                      "Print, or --install, NoClick's MCP server for a coding agent's harness.", auth=False)
    mcp.add_argument("harness", nargs="?", choices=("claude", "codex", "cursor"),
                     help="Claude Code (.mcp.json here), Codex (~/.codex/config.toml) or Cursor (.cursor/mcp.json "
                          "here); none prints the server's URL and how it signs in.")
    mcp.add_argument("--install", action="store_true", help="Write it into the harness's config.")
    mcp.add_argument("--oauth", action="store_true",
                     help="Sign in from the harness in a browser, instead of with a key from the environment.")
    mcp.add_argument("--key-env", default=API_KEY_ENV, metavar="VAR",
                     help=f"The environment variable holding the key (default {API_KEY_ENV}).")
    mcp.add_argument("--dir", default=".", help="The project folder (default: here).")
