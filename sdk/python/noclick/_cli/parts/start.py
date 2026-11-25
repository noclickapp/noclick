"""Start: ``noclick setup <code>`` (a setup code for a key, no browser) and ``noclick init`` (a folder becomes an
app: from a template, or drafted by the app's coding agent from what you describe), linking the folder."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any, Dict

from ... import cli
from ..._client import API_URL_ENV, DEFAULT_BASE_URL, resolve_client
from ...exceptions import NotFound
from ...key import Key
from ...project import Project
from ...repo import Repo
from .. import link, output as out, templates

# How long init waits for the coding agent's draft by default: a first app takes it a few minutes.
DRAFT_TIMEOUT_S = 900.0
# The branch the app's coding agent pushes its work to, outside a live session.
CODER_BRANCH = "noclick-code"
_NAME = re.compile(r"[^a-z0-9-]+")


def cmd_setup(args: argparse.Namespace) -> int:
    api_url = (os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
    store = cli.key_store(args.store)
    key = Key.redeem_setup_code(args.code, base_url=api_url)
    cli.keep_key(args.profile, args.store, store, api_url, {
        "key": key.secret, "key_id": key.id, "key_name": key.name, "email": key.raw.get("email")})
    out.note("Next: noclick init, or noclick deploy in your app's folder.")
    return 0


def _app_name(args: argparse.Namespace, folder: Path) -> str:
    name = args.name or _NAME.sub("-", folder.resolve().name.lower()).strip("-")
    if not name:
        raise cli.CommandError("Name the app: this folder's name makes none.", next_step="noclick init <name>")
    return name


def _write(folder: Path, files: Dict[str, str]) -> None:
    taken = sorted(path for path in files if (folder / path).exists())
    if taken:
        raise cli.CommandError(f"The folder already has {', '.join(taken)}: init writes only new files.",
                               next_step="Run it in an empty folder, or pass --dir <new folder>.")
    for path, text in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_text(text)


def _git_init(folder: Path) -> None:
    if not (folder / ".git").exists():
        cli._git("init", "--quiet", "--initial-branch", "main", cwd=str(folder))


def _made(name: str) -> Project:
    repo = Repo.from_name(name, create_if_missing=True)
    return Project.from_name(name, repo=repo, create_if_missing=True)


def _fetch_draft(folder: Path, repo: Repo, branch: str) -> str:
    """Check the coding agent's branch out in ``folder`` as main, through a remote that never lands in the folder's
    git config or the process list; its head's sha."""
    _git_init(folder)
    env = cli._repo_remote(repo.clone_url(write=False, ttl_s=600))
    cli._git("fetch", "--quiet", "noclick-deploy", f"refs/heads/{branch}", cwd=str(folder), env=env)
    cli._git("checkout", "--quiet", "-B", "main", "FETCH_HEAD", cwd=str(folder))
    return cli._git("rev-parse", "HEAD", cwd=str(folder))


def cmd_init(args: argparse.Namespace) -> int:
    if args.fetch:
        folder = Path(args.dir)
        name = link.app_name(args.name, start=folder)
        sha = _fetch_draft(folder, Project.from_name(name).repo, CODER_BRANCH)
        out.note(f"Checked the coding agent's draft of {name} out here ({sha[:7]}). Next: noclick deploy")
        out.value_last(name)
        return 0
    if bool(args.template) == bool(args.describe):
        raise cli.CommandError("Say what to start from: --template <name> or --describe \"what you want\".",
                               next_step=f"Templates: {', '.join(templates.TEMPLATES)}. Or: noclick init --describe "
                                         "\"a page that takes bookings\"")
    folder = Path(args.dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = _app_name(args, folder)
    if args.template:
        if args.template not in templates.TEMPLATES:
            raise cli.CommandError(f"There's no template {args.template!r}.",
                                   next_step=f"Pick one of: {', '.join(templates.TEMPLATES)}")
        _write(folder, templates.files_of(args.template, name))
    elif any(p.name not in (".git", link.FOLDER) for p in folder.iterdir()):
        raise cli.CommandError("--describe drafts the app into an empty folder, and this one has files.",
                               next_step="Run it in a new folder (--dir <new folder>), or start from your files with "
                                         "noclick deploy --create.")
    app = _made(name)
    link.write(name, app_id=app.id, api_url=resolve_client(None).base_url, root=folder)
    out.note(f"Linked {folder.resolve()} to the app {name} (.noclick/project.json).")
    if args.template:
        _git_init(folder)
        out.note(f"Wrote the {args.template} template: {templates.TEMPLATES[args.template]['about']}")
        out.note("Next: noclick deploy")
        out.value_last(name)
        return 0
    out.note("Handing what you described to the app's coding agent: it writes the app and pushes it (its work is "
             "charged to your account, at what its model costs).")
    job = app.live.change(args.describe, title=f"Draft {name}")
    if args.no_wait:
        out.value_last(job.id)
        out.note(f"Drafting. Wait for it with: noclick wait {job.id}, then check it out here: noclick init --fetch")
        return 0
    reply = job.wait(timeout=args.timeout)
    out.note(reply.text)
    branch = ((reply.raw.get("code") or {}) if isinstance(reply.raw.get("code"), dict) else {}).get("branch") \
        or CODER_BRANCH
    try:
        sha = _fetch_draft(folder, app.repo, branch)
    except cli.CommandError as missed:
        raise NotFound(f"The coding agent pushed nothing to {branch}: {missed.message}",
                       next_step=f"Read what it said above, then ask again: noclick init --describe \"...\" --dir "
                                 f"{args.dir}") from None
    out.note(f"Checked its draft out here ({sha[:7]}). Next: noclick deploy")
    out.value_last(name)
    return 0


def register(kit: Any) -> None:
    setup = kit.command(kit.commands, "setup", cmd_setup,
                        "Redeem a setup code (nc_setup_..., from the console's quickstart) for a key, no browser.",
                        auth=False)
    setup.add_argument("code", help="The one-time setup code.")
    setup.add_argument("--store", choices=("auto", "keychain", "file"), default="auto",
                       help="Where to keep the key, as noclick login does (default: the keychain, else a file).")
    init = kit.command(kit.commands, "init", cmd_init,
                       "Make a folder an app: from a template, or drafted from what you describe. Links the folder.")
    init.add_argument("name", nargs="?", help="The app's name (default: the folder's).")
    init.add_argument("--template", metavar="NAME",
                      help=f"Start from a template: {', '.join(f'{k} ({v['about']})' for k, v in templates.TEMPLATES.items())}")
    init.add_argument("--describe", metavar="TEXT", help="What the app should be: its coding agent drafts it.")
    init.add_argument("--dir", default=".", help="The folder (default: here).")
    init.add_argument("--no-wait", action="store_true", help="With --describe: print the draft's operation id.")
    init.add_argument("--fetch", action="store_true",
                      help="Check out the coding agent's draft of the linked app here (after --no-wait).")
    init.add_argument("--timeout", type=float, default=DRAFT_TIMEOUT_S, metavar="SECONDS",
                      help=f"With --describe: how long to wait for the draft (default {DRAFT_TIMEOUT_S:.0f}).")
