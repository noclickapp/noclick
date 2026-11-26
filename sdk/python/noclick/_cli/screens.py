"""What the CLI shows before a command runs: ``noclick`` alone, ``noclick --help`` (``--all`` for every API area),
a command it doesn't have, and a command's examples. The words are here once; ``scripts/cli_manifest.py`` writes
them into the manifest's ``screens``, which the TypeScript CLI draws the same screens from."""

from __future__ import annotations

import difflib
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

INTRO = "NoClick's CLI: ship a folder as an app, configure and operate it, and reach every API operation."

# The curated commands by what they're for, as the CLI's guide has them; every top-level command is in one.
SECTIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Start", ("signup", "setup", "login", "whoami", "logout", "init", "link", "unlink")),
    ("Ship", ("deploy", "status", "open", "releases", "rollback", "promote", "delete", "live")),
    ("Configure", ("secret", "env", "settings", "bind", "domains")),
    ("Operate", ("logs", "db", "bucket", "wait", "ops", "estimate", "agents", "users", "machines", "webhooks")),
    ("Everything else", ("api", "describe", "help")),
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
    }


def _rows(rows: Iterable[Tuple[str, str]], width: int) -> List[str]:
    return [f"  {name:<{width}}  {text}" for name, text in rows]


def signed_in(email: Optional[str], *, from_env: Optional[str] = None) -> Optional[str]:
    if from_env:
        return f"Signed in with {from_env}"
    return f"Signed in as {email}" if email else None


def first(*, signed_in: Optional[str], linked_app: Optional[str]) -> str:
    """``noclick`` alone: what it is, the three things to do first, where to go next. Signed in (``signed_in``'s
    words), who you are and the folder's app in place of signing in."""
    lines = [INTRO, ""]
    start = list(FIRST)
    if signed_in:
        lines.append(signed_in
                     + (f"; this folder is linked to {linked_app}." if linked_app else "."))
        start = start[1:]
    rows = [*start, *NEXT]
    width = max(len(name) for name, _ in rows)
    shown = _rows(start, width)
    if not signed_in:  # beside signing in: an agent with no person to sign in
        shown.insert(1, f"  {SIGNED_OUT}")
    lines += ["Start here:", *shown, "", "Then:", *_rows(NEXT, width)]
    return "\n".join(lines)


def commands(summaries: Dict[str, str], areas: Optional[Dict[str, int]]) -> str:
    """The commands by section, one line each, then the API's areas: one line, or (``--all``) each of them."""
    shown = [*summaries, AREAS[0], *(areas or {})]
    width = max(len(name) for name in shown)
    lines: List[str] = []
    for name, names in SECTIONS:
        lines += [f"{name}:", *_rows(((n, summaries[n]) for n in names if n in summaries), width)]
        if name == "Everything else":
            if areas is None:
                lines += _rows([AREAS], width)
            else:
                lines += _rows(((area, f"{count} API operation{'' if count == 1 else 's'}: noclick {area} --help lists them.")
                                for area, count in sorted(areas.items())), width)
        lines.append("")
    return "\n".join(lines).rstrip()


def unknown(word: str, *, within: Sequence[str], curated: Sequence[str], areas: Sequence[str]) -> str:
    """A command line naming a command there isn't: the closest curated commands, else the closest API areas (under
    a group, its commands and operations alike)."""
    said = " ".join([*within, word])
    pools = [[*curated, *areas]] if within else [list(curated), list(areas)]
    near = next((found for found in (difflib.get_close_matches(word, pool, n=3) for pool in pools) if found), [])
    prefix = " ".join(["noclick", *within])
    lines = [f"Unknown command '{said}'." + (
        f" Did you mean: {', '.join(' '.join([*within, n]) for n in near)}?" if near else "")]
    lines.append(f"Every command: {prefix} --help")
    return "\n".join(lines)


def examples(lines: Sequence[str]) -> str:
    return "\n".join(["examples:", *(f"  {line}" for line in lines)])
