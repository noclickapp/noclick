"""What the CLI shows before a command runs: ``noclick`` alone, ``noclick --help`` (``--all`` for every API area),
a command it doesn't have, and a command's examples. The words are here once; ``scripts/cli_manifest.py`` writes
them into the manifest's ``screens``, which the TypeScript CLI draws the same screens from."""

from __future__ import annotations

import difflib
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .style import Style, clip

PLAIN = Style()

INTRO = "NoClick's CLI: ship a folder as an app, configure and operate it, and reach every API operation."

# The curated commands by what they're for, as the CLI's guide has them; every top-level command is in one.
SECTIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Start", ("signup", "setup", "login", "whoami", "logout", "profile", "init", "link", "unlink")),
    ("Ship", ("deploy", "status", "open", "releases", "rollback", "promote", "delete", "live")),
    ("Configure", ("secret", "env", "bind", "domains")),
    ("Operate", ("resources", "logs", "db", "bucket", "wait", "estimate", "agents", "users", "machines", "shell", "webhooks",
                 "dashboard")),
    ("Everything else", ("api", "describe", "help", "completion", "changelog")),
    ("Teach", ("docs", "skill", "mcp")),
)
AREAS = ("<area> <operation>",
         "Every /v1 operation; noclick --help --all lists the areas, noclick <area> --help its operations.")

FIRST: Tuple[Tuple[str, str], ...] = (
    ("noclick login", "Sign in from a browser (or noclick setup <code>, with a code from the console's Quickstart)."),
    ("noclick deploy", "Ship this folder as an app and print its live URL."),
    ("noclick status", "The app on one screen: its URLs, live release, health, errors and spend."),
)
SIGNED_OUT = "No account? noclick signup --accept-terms"
NEXT: Tuple[Tuple[str, str], ...] = (
    ("noclick ls", "What your account has, by kind (the same as noclick resources)."),
    ("noclick --help", "Every command, by what it's for."),
    ("noclick docs cli", "The CLI's guide, as Markdown."),
    ("noclick help --json", "Every command, its flags and examples, as data."),
)


# noclick signup: the terms it accepts, what its --agent is by default (the first of these set in the
# environment names the harness running it, else "cli"), and what works before a person claims the account.
TERMS = ("https://noclick.com/legal/developer-terms", "https://noclick.com/legal/acceptable-use")
HARNESSES: Tuple[Tuple[str, str], ...] = (
    ("CLAUDECODE", "claude-code"), ("CODEX_THREAD_ID", "codex"), ("CODEX_SANDBOX", "codex"),
    ("OPENCODE", "opencode"), ("GEMINI_CLI", "gemini-cli"), ("CURSOR_AGENT", "cursor"),
)
WORKS = ("Works now: making agents, workflows, channels, dicts, queues, memories and webhooks, and every read.")


def harness(env: Dict[str, str]) -> str:
    """The harness running the CLI, by what it sets in the environment, else ``cli``."""
    return next((name for var, name in HARNESSES if env.get(var)), "cli")


def unclaimed(claim_url: Optional[str]) -> str:
    return "unclaimed: give your person " + (
        claim_url or "a claim link (noclick api POST /v1/agent_signups/current/claim_link makes one)")


# noclick resources: every kind of thing the account holds that runs, is kept or is paid for, as the app's Resources
# page lists them (its ids), and sandboxes and volumes beside them. Each column is a header, the field it reads (a dot
# goes into an object; "$spend" is this month's spend from GET /v1/usage?group_by=project) and how it's shown.
RESOURCE_KINDS: Tuple[Dict[str, Any], ...] = (
    {"kind": "apps", "title": "Websites", "path": "/v1/projects",
     "columns": [["NAME", "name", "text"], ["URL", "url", "text"], ["STATUS", "production.status", "status"],
                 ["THIS MONTH", "$spend", "usd"]]},
    {"kind": "machines", "title": "Machines", "path": "/v1/machines",
     "columns": [["NAME", "name", "text"], ["STATUS", "status", "status"], ["SIZE", "size", "text"],
                 ["REGION", "region", "text"], ["A MONTH", "monthly_usd", "usd"]]},
    {"kind": "databases", "title": "Databases", "path": "/v1/databases",
     "columns": [["NAME", "name", "text"], ["ENGINE", "engine", "text"], ["STATUS", "status", "status"],
                 ["SIZE", "size_bytes", "bytes"], ["TABLES", "table_count", "text"]]},
    {"kind": "storage", "title": "Buckets", "path": "/v1/buckets",
     "columns": [["NAME", "name", "text"], ["PUBLIC", "public", "bool"], ["SIZE", "size_bytes", "bytes"],
                 ["OBJECTS", "object_count", "text"]]},
    {"kind": "repos", "title": "Repos", "path": "/v1/repos",
     "columns": [["NAME", "name", "text"], ["BRANCH", "default_branch", "text"], ["SIZE", "size_bytes", "bytes"]]},
    {"kind": "domains", "title": "Domains", "path": "/v1/domains",
     "columns": [["NAME", "name", "text"], ["STATUS", "status", "status"], ["EXPIRES", "expires_at", "date"],
                 ["A YEAR", "renewal_usd", "usd"]]},
    {"kind": "numbers", "title": "Phone numbers", "path": "/v1/phone_numbers",
     "columns": [["NUMBER", "number", "text"], ["NAME", "name", "text"], ["A MONTH", "monthly_usd", "usd"]]},
    {"kind": "email", "title": "Inboxes", "path": "/v1/inboxes",
     "columns": [["ADDRESS", "address", "text"], ["NAME", "name", "text"]]},
    {"kind": "sandboxes", "title": "Sandboxes", "path": "/v1/sandboxes", "query": {"status": "live"},
     "columns": [["ID", "id", "text"], ["STATUS", "status", "status"], ["IMAGE", "image", "text"],
                 ["REGION", "region", "text"]]},
    {"kind": "volumes", "title": "Volumes", "path": "/v1/volumes",
     "columns": [["NAME", "name", "text"], ["SIZE", "size_bytes", "bytes"], ["FILES", "file_count", "text"]]},
)
# An error's words as the command line says them (``cli._for_the_terminal``, the TypeScript CLI's ``said.ts``):
# what isn't there, by its kind (the SDK's ``details.kind``), and the command that makes it, or the API route that
# does (the command for it read from the spec); a kind the command line calls something else; why the API couldn't
# be reached, as the network said it (a code, or words in it), said plainly.
MAKES = {"project": ("Create it with", "noclick deploy {name} --create"),
         "database": ("Create it with", "noclick db create {name}"),
         "bucket": ("Create it with", "noclick bucket create {name}"),
         "domain": ("See if it's free to buy", "noclick domains search {name}")}
MADE_BY = {"agent": "/v1/agents", "browser_profile": "/v1/browser_profiles", "card": "/v1/cards",
           "channel": "/v1/channels", "dict": "/v1/dicts", "inbox": "/v1/inboxes", "machine": "/v1/machines",
           "mcp_server": "/v1/mcp_servers", "memory": "/v1/memories", "phone_number": "/v1/phone_numbers",
           "queue": "/v1/queues", "repo": "/v1/repos", "secret": "/v1/secrets", "skill": "/v1/skills",
           "volume": "/v1/volumes", "workspace": "/v1/workspaces"}
KIND_WORDS = {"project": "app"}
UNREACHABLE = (("ECONNREFUSED", "connection refused"), ("All connection attempts failed", "connection refused"),
               ("Connection refused", "connection refused"), ("ENOTFOUND", "no such host"),
               ("EAI_AGAIN", "no such host"), ("Name or service not known", "no such host"),
               ("nodename nor servname", "no such host"), ("ETIMEDOUT", "timed out"),
               ("UND_ERR_CONNECT_TIMEOUT", "timed out"), ("timed out", "timed out"), ("ECONNRESET", "connection reset"))
DEFAULT_API = "https://api.noclick.com"


def unreachable(api_url: str, cause: str) -> Tuple[str, str]:
    """An API that couldn't be reached, said plainly: its host (its whole URL when NOCLICK_API_URL names another)
    and why, as the network said it; and what to do."""
    why = next((said for found, said in UNREACHABLE if found.lower() in (cause or "").lower()), cause or "no answer")
    default = api_url.rstrip("/") == DEFAULT_API
    where = DEFAULT_API.split("//", 1)[1] if default else api_url
    return (f"Can't reach {where} ({why}).",
            "Check your network, then try again." if default else
            f"Check your network, and NOCLICK_API_URL ({api_url}), then try again.")


# A word that means another, wherever the command line has it: ``noclick ls`` is ``noclick resources``, and ``ls``
# under a group with ``list`` and no ``ls`` of its own is ``list``.
TOP_ALIASES = {"ls": "resources"}
GROUP_ALIASES = {"ls": "list"}
# Older spellings of a command, which keep working and are listed nowhere: the words, the command they now are, and
# what the old one's leading arguments become (``--app``: the next argument is the app; ``=``: the next two are one
# KEY=value); the rest is passed on as it was. ``VALUED`` are the flags among them that take a value.
OLD_SPELLINGS: Tuple[Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]], ...] = (
    (("settings", "list"), ("env", "ls"), ("--app",)),
    (("settings", "set"), ("env", "set"), ("--app", "=")),
    (("settings", "delete"), ("env", "rm"), ("--app",)),
    (("ops", "wait"), ("wait",), ()),
    (("settings",), ("env",), ()),
    (("ops",), ("wait",), ()),
)
VALUED = ("--user", "--timeout", "--profile", "--color")


def spelled_out(words: Sequence[str]) -> List[str]:
    """``words`` (the command's own, past the global flags) with an older spelling as the command it now is."""
    for old, new, leading in OLD_SPELLINGS:
        if tuple(words[:len(old)]) != old:
            continue
        rest, out, flags, i = list(words[len(old):]), [], [], 0
        positional: List[str] = []
        while i < len(rest):
            if rest[i].startswith("-") and rest[i] != "-":
                flags.append(rest[i])
                if rest[i] in VALUED and i + 1 < len(rest):
                    flags.append(rest[i + 1])
                    i += 1
            else:
                positional.append(rest[i])
            i += 1
        for how in leading:
            if how == "--app" and positional:
                flags += ["--app", positional.pop(0)]
            elif how == "=" and len(positional) >= 2:
                out.append(f"{positional.pop(0)}={positional.pop(0)}")
        return [*new, *out, *positional, *flags]
    return list(words)


def manifest(summaries: Dict[str, str]) -> Dict[str, Any]:
    """The words, as the manifest keeps them: each section's commands with their summaries (``summaries``, by
    top-level command)."""
    return {
        "intro": INTRO,
        "sections": [{"name": name, "commands": [[n, summaries[n]] for n in names]} for name, names in SECTIONS],
        "areas": list(AREAS),
        "first": [list(row) for row in FIRST],
        "next": [list(row) for row in NEXT],
        "signed_out": SIGNED_OUT,
        "signup": {"terms": list(TERMS), "harnesses": [list(row) for row in HARNESSES], "works": WORKS},
        "resources": [dict(kind) for kind in RESOURCE_KINDS],
        "aliases": {"top": TOP_ALIASES, "group": GROUP_ALIASES,
                    "old": [[list(old), list(new), list(leading)] for old, new, leading in OLD_SPELLINGS],
                    "valued": list(VALUED)},
        "said": {"makes": {kind: list(made) for kind, made in MAKES.items()}, "made_by": MADE_BY, "kind_words": KIND_WORDS,
                 "unreachable": [list(row) for row in UNREACHABLE], "default_api": DEFAULT_API},
    }


def _rows(rows: Iterable[Tuple[str, str]], width: int, s: Style = PLAIN,
          name_as: Optional[Callable[[str], str]] = None) -> List[str]:
    if not s.on:
        return [f"  {name:<{width}}  {text}" for name, text in rows]
    paint = name_as or s.accent
    room = max(s.width() - width - 4, 20)  # one line each: a description too long for the terminal is cut
    return [f"  {paint(name.ljust(width))}  {s.dim(clip(text, room))}" for name, text in rows]


def signed_in(email: Optional[str], *, from_env: Optional[str] = None) -> Optional[str]:
    if from_env:
        return f"Signed in with {from_env}"
    return f"Signed in as {email}" if email else None


def first(*, signed_in: Optional[str], linked_app: Optional[str], s: Style = PLAIN) -> str:
    """``noclick`` alone: what it is, the three things to do first, where to go next. Signed in (``signed_in``'s
    words), who you are and the folder's app in place of signing in."""
    lines = [s.bold(INTRO), ""]
    start = list(FIRST)
    if signed_in:
        said = signed_in + (f"; this folder is linked to {linked_app}." if linked_app else ".")
        lines.append(f"{s.ok('✓')} {said}" if s.on else said)
        if s.on:
            lines.append("")
        start = start[1:]
    rows = [*start, *NEXT]
    width = max(len(name) for name, _ in rows)
    shown = _rows(start, width, s, s.link)
    if not signed_in:  # beside signing in: an agent with no person to sign in
        word, command = SIGNED_OUT.split("? ", 1)
        shown.insert(1, f"  {s.dim(word + '?')} {s.link(command)}" if s.on else f"  {SIGNED_OUT}")
    lines += [*s.section("Start here"), *shown, "", *s.section("Then"), *_rows(NEXT, width, s, s.link)]
    return "\n".join(lines)


def commands(summaries: Dict[str, str], areas: Optional[Dict[str, int]], s: Style = PLAIN) -> str:
    """The commands by section, one line each, then the API's areas: one line, or (``--all``) each of them."""
    shown = [*summaries, AREAS[0], *(areas or {})]
    width = max(len(name) for name in shown)
    lines: List[str] = []
    for name, names in SECTIONS:
        lines += [*s.section(name), *_rows(((n, summaries[n]) for n in names if n in summaries), width, s)]
        if name == "Everything else":
            if areas is None:
                lines += _rows([AREAS], width, s)
            else:
                lines += _rows(((area, f"{count} API operation{'' if count == 1 else 's'}: noclick {area} --help lists them.")
                                for area, count in sorted(areas.items())), width, s)
        lines.append("")
    return "\n".join(lines).rstrip()


def unknown(word: str, *, within: Sequence[str], curated: Sequence[str], areas: Sequence[str],
            s: Style = PLAIN) -> str:
    """A command line naming a command there isn't: the closest curated commands, else the closest API areas (under
    a group, its commands and operations alike)."""
    said = " ".join([*within, word])
    if len(word.split()) > 1:  # quoted as one argument ("projects list"): no command has a space in its name
        return "\n".join([s.error(f"Unknown command '{said}'.") + " It came as one argument; pass its words apart:",
                          f"  {s.link(' '.join(['noclick', *within, *word.split()]))}"])
    pools = [[*curated, *areas]] if within else [list(curated), list(areas)]
    near = next((found for found in (difflib.get_close_matches(word, pool, n=3) for pool in pools) if found), [])
    prefix = " ".join(["noclick", *within])
    lines = [s.error(f"Unknown command '{said}'.") + (
        f" Did you mean: {', '.join(s.link(' '.join([*within, n])) for n in near)}?" if near else "")]
    lines.append(f"{s.dim('Every command:')} {s.link(prefix + ' --help')}")
    return "\n".join(lines)


def examples(lines: Sequence[str], s: Style = PLAIN) -> str:
    return "\n".join([*(s.section("Examples") if s.on else ["examples:"]), *(f"  {s.link(line)}" for line in lines)])
