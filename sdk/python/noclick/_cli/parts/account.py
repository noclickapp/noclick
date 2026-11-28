"""Where you work from: ``noclick profile`` (the logins this machine keeps, and which one commands use),
``noclick completion`` (Tab for your shell), ``noclick dashboard`` (the console in a browser) and ``noclick changelog``
(what changed lately)."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from typing import Any, Dict, List, Optional

import httpx

from ... import cli
from ..._client import API_KEY_ENV, CONSOLE_BASE_URL, DEFAULT_BASE_URL

from ...exceptions import NotFound
from .. import changelog, completion, output as out
from ..commands import UsageError

CONSOLE_URL_ENV = "NOCLICK_CONSOLE_URL"


# --- profiles ----------------------------------------------------------------------------------------------------


def _profile_view(name: str, login: Dict[str, Any], active: Optional[str]) -> Dict[str, Any]:
    return {"name": name, "active": name == active, "email": login.get("email"), "key_name": login.get("key_name"),
            "key_prefix": login.get("key_prefix"), "store": login.get("store"),
            "api_url": login.get("api_url") or DEFAULT_BASE_URL}


def _stored() -> Dict[str, Dict[str, Any]]:
    return {name: login for name, login in cli._read_config().get("profiles", {}).items() if login.get("store")}


def _env_note() -> None:
    if os.environ.get(API_KEY_ENV):
        out.note(f"{API_KEY_ENV} is set in this shell: commands use it, whichever profile is active.")


def cmd_profile_list(args: argparse.Namespace) -> int:
    active, why = args.profile, args.profile_source
    rows = [_profile_view(name, login, active) for name, login in sorted(_stored().items())]
    if args.json:
        out.print_json({"data": rows, "active": active, "active_source": why})
        return 0
    out.table(["", "PROFILE", "ACCOUNT", "KEY", "API"],
              [("*" if r["active"] else "", r["name"], r["email"] or "-", r["key_name"] or r["key_prefix"] or "-",
                r["api_url"]) for r in rows], empty="No stored logins: noclick login signs one in.")
    if rows:
        out.note(f"* is active ({cli.PROFILE_SOURCES[why]}). Switch: noclick profile use <name>")
    if active not in {r["name"] for r in rows}:
        out.note(f"The active profile, {active} ({cli.PROFILE_SOURCES[why]}), has no stored login.")
    _env_note()
    return 0


def cmd_profile_use(args: argparse.Namespace) -> int:
    stored = _stored()
    if args.name not in stored:
        raise out.run(NotFound(f"No stored login is called {args.name}"
                                  + (f" (stored: {', '.join(sorted(stored))})." if stored else "."),
                                  next_step="Sign in under that name."), [f"noclick login --profile {args.name}"])
    config = cli._read_config()
    config[cli.DEFAULT_PROFILE_KEY] = args.name
    cli._write_config(config)
    if args.json:
        out.print_json({"active": args.name, "email": stored[args.name].get("email")})
    else:
        email = stored[args.name].get("email")
        out.line(f"Commands now use the profile {args.name}{f' ({email})' if email else ''}.")
    if os.environ.get(cli.PROFILE_ENV) and os.environ[cli.PROFILE_ENV] != args.name:
        out.note(f"{cli.PROFILE_ENV}={os.environ[cli.PROFILE_ENV]} is set in this shell and still wins: unset it.")
    _env_note()
    return 0


def cmd_profile_show(args: argparse.Namespace) -> int:
    active, why = args.profile, args.profile_source
    name = args.name or active
    login = _stored().get(name)
    if login is None:
        raise out.run(NotFound(f"No stored login is called {name}.", next_step="Sign in under that name."),
                         [f"noclick login --profile {name}"])
    view = {**_profile_view(name, login, active), **({"active_source": why} if name == active else {})}
    if args.json:
        out.print_json(view)
        return 0
    where = "the OS keychain" if login.get("store") == "keychain" else "a file only you can read"
    for label, value in (("Profile", f"{name} ({cli.PROFILE_SOURCES[why]})" if name == active else name),
                         ("Account", view["email"]),
                         ("Key", f"{view['key_name'] or 'unnamed'} ({view['key_prefix'] or '?'}…), in {where}"),
                         ("API", view["api_url"])):
        if value:
            out.line(f"{label:<8} {value}")
    _env_note()
    return 0


# --- completion ----------------------------------------------------------------------------------------------------


def cmd_completion(args: argparse.Namespace) -> int:
    if not args.install:
        sys.stdout.write(completion.SCRIPTS[args.shell])
        return 0
    for line in completion.install(args.shell):
        out.line(line)
    out.note("Open a new shell to use it.")
    return 0


# --- the console ---------------------------------------------------------------------------------------------------


def _console(api_url: str) -> str:
    given = os.environ.get(CONSOLE_URL_ENV)
    if given:
        return given.rstrip("/")
    if api_url.rstrip("/") != DEFAULT_BASE_URL:
        raise cli.CommandError(f"This profile's API ({api_url}) has no console NoClick knows the address of.",
                               next_step=f"Set {CONSOLE_URL_ENV} to its address.")
    return CONSOLE_BASE_URL


def _can_open() -> bool:
    """Whether a browser can be opened here: a terminal on a machine with a display."""
    if not sys.stdout.isatty():
        return False
    return sys.platform in ("darwin", "win32") or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _open(url: str) -> bool:
    return webbrowser.open(url)


def cmd_dashboard(args: argparse.Namespace) -> int:
    creds = cli.resolve_credentials(args.profile)
    url = _console(creds.api_url)
    if args.app:
        signed = cli._signed_in(args.profile)
        cli.configure(api_key=signed.key, base_url=signed.api_url)
        url = f"{url}/resources/apps/{cli._app(args.app).id}"
    opened = not args.json and _can_open() and _open(url)
    if args.json:
        out.print_json({"url": url, "opened": False})
        return 0
    if opened:
        out.note("Opened it in your browser.")
    out.line(url)
    return 0


# --- the changelog -------------------------------------------------------------------------------------------------


def _changes() -> List[Dict[str, Any]]:
    url = changelog.page_url()
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": cli.USER_AGENT})
    except httpx.HTTPError as err:
        raise cli.CommandError(f"Couldn't read the changelog at {url}: {err}.",
                               next_step=f"Check your connection, or {changelog.DOCS_URL_ENV}.") from None
    if response.status_code != 200:
        raise cli.CommandError(f"Couldn't read the changelog at {url}: it answered {response.status_code}.",
                               next_step=f"Check {changelog.DOCS_URL_ENV}, which names the docs it's read from.")
    return changelog.parse(response.text, changelog.docs_url())


def cmd_changelog(args: argparse.Namespace) -> int:
    entries = _changes()
    if args.change:
        found = changelog.find(entries, args.change)
        if not found:
            raise out.run(NotFound(f"No change in the changelog is called {args.change!r}.",
                                      next_step="List the changes."), ["noclick changelog"])
        if len(found) > 1:
            raise UsageError(f"{len(found)} changes match {args.change!r}: "
                             f"{', '.join(changelog.ref(e, entries) for e in found[:5])}{', …' if len(found) > 5 else ''}.",
                             next_step="Name one.", run=[f"noclick changelog {changelog.ref(found[0], entries)}"])
        entry = found[0]
        if args.json:
            out.print_json(entry)
            return 0
        kind = " · ".join(v for v in (entry["kind"] and entry["kind"].capitalize(), entry["areas"]) if v)
        out.line(f"## {entry['title']}\n{entry['date']}{f' · {kind}' if kind else ''}\n\n{entry['body']}")
        out.note(f"On the web: {entry['url']}")
        return 0
    shown = entries[:args.limit]
    if args.json:
        out.print_json({"data": shown})
        return 0
    out.table(["DATE", "CHANGE"], [(e["date"], e["title"]) for e in shown], empty="No changelog entries.")
    if shown:
        out.note(f"Read one whole: noclick changelog {changelog.ref(shown[0], entries)}")
    return 0


def register(kit: Any) -> None:
    profile = kit.group("profile", "List the logins this machine keeps and choose the one commands use.")
    listed = kit.command(profile, "list", cmd_profile_list,
                         "Each stored login, its account and key; * marks the one commands use.",
                         auth=False, parents=[kit.as_json])
    use = kit.command(profile, "use", cmd_profile_use,
                      "Make a stored login the one commands use (--profile and NOCLICK_PROFILE still win).",
                      auth=False, parents=[kit.as_json])
    use.add_argument("name", help="The profile's name, as noclick profile list shows it.")
    show = kit.command(profile, "show", cmd_profile_show,
                       "A stored login's account, key and API (default: the active one).",
                       auth=False, parents=[kit.as_json])
    show.add_argument("name", nargs="?", help="The profile's name (default: the active one).")

    shell = kit.command(kit.commands, "completion", cmd_completion,
                        "Print, or --install, Tab completion for your shell.", auth=False)
    shell.add_argument("shell", choices=completion.SHELLS, help="Your shell.")
    shell.add_argument("--install", action="store_true",
                       help="Put it where the shell loads it (running it again changes nothing).")

    console = kit.command(kit.commands, "dashboard", cmd_dashboard,
                          "Open the console in your browser (an app's page when named); prints the URL.",
                          auth=False, parents=[kit.as_json])
    console.add_argument("app", nargs="?", help="The app's name.")

    changes = kit.command(kit.commands, "changelog", cmd_changelog,
                          "What changed in NoClick lately, newest first, or one change whole (no key needed).",
                          auth=False, parents=[kit.as_json])
    changes.add_argument("change", nargs="?", help="A change's title or slug: print it whole.")
    changes.add_argument("--limit", type=int, default=10, help="At most this many (default 10).")
