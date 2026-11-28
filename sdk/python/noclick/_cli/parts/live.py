"""``noclick live``: the app's live session as an agent's development loop. The site runs on a dev server in a
container with the app's real bindings, at the app's own URL; what's pushed to the ``noclick-live`` branch (``noclick
live push``) shows at once, and ``noclick live end`` builds, checks and deploys it. No local toolchain."""

from __future__ import annotations

import argparse
from typing import Any

from ... import cli
from ...exceptions import NotAvailable
from ...project import Deployment, Project
from .. import link, output as out, spend

LIVE_BRANCH = "noclick-live"
# How long `noclick live` waits for a starting session by default (a first one in a place takes a few minutes).
START_TIMEOUT_S = 300.0


def _app(args: argparse.Namespace) -> Project:
    return cli._app(link.app_name(getattr(args, "project", None) or getattr(args, "app", None)))


def _print_session(session: Any, as_json: bool) -> None:
    if as_json:
        out.print_json(session)
        return
    out.note(f"Session {session.id}: {session.state}{f' ({session.phase})' if session.phase else ''}")
    edits = session.edits
    if edits.count:
        out.note(f"  edits: {edits.count} ({edits.hot} in place, {edits.reload} reloaded, {edits.error} failed)")
    if session.git:
        out.note(f"  branch {session.git.get('branch')} at {str(session.git.get('head') or '')[:7]}"
                 f"{', conflict' if session.git.get('conflict') else ''}")
    if session.error:
        out.note(f"  error: {session.error.get('message')}")


def cmd_live_start(args: argparse.Namespace) -> int:
    app = _app(args)
    hours = args.hours
    spend.check([{"kind": "live_editing", "usage": {"hours": hours}}], args.max_usd,
                what=f"A session of up to {hours:g} hours", per="at most")
    status = app.live.status()
    if not status.supported:
        raise out.run(NotAvailable(f"{app.name} can't be edited live: {status.unsupported_reason}",
                                   next_step="Deploy it with noclick deploy instead."), ["noclick deploy"])
    if not status.enabled:
        app.update(live_editing=True)
        out.note(f"Turned live editing on for {app.name}.")
    session = app.live.start(wait=True, limits={"max_session_s": int(hours * 3600)})
    enter = session.enter_url
    ends = cli._clock() + args.timeout
    while session.state == "warming" and cli._clock() < ends:
        cli._sleep(cli.POLL_S)
        session = app.live.status().session or session
    if args.json:
        out.print_json(session)
        return 0
    _print_session(session, False)
    if session.state == "warming":
        out.note(f"Still starting after {args.timeout:g}s: the link below shows it once it's live "
                 "(noclick live status reads it again).")
    out.note(f"The app's URL, {session.url}, shows production to everyone but whoever opens the link below.")
    out.note("Push edits with: noclick live push (they show at once). Ship them with: noclick live end")
    out.value_last(enter or session.url)
    return 0


def cmd_live_status(args: argparse.Namespace) -> int:
    status = _app(args).live.status()
    if args.json:
        out.print_json(status)
        return 0
    if not status.supported:
        out.note(f"Can't be edited live: {status.unsupported_reason}")
        return 0
    if status.session is None:
        out.note("No session yet: start one with noclick live")
        return 0
    _print_session(status.session, False)
    out.value_last(status.session.url if status.session.open else None)
    return 0


def cmd_live_push(args: argparse.Namespace) -> int:
    app = _app(args)
    root = cli._git("rev-parse", "--show-toplevel")
    if cli._git("status", "--porcelain", "--untracked-files=no", cwd=root):
        raise cli.CommandError("Your checkout has uncommitted changes.",
                               next_step="Commit them: live push sends the commit you're on.")
    sha = cli._git("rev-parse", "HEAD", cwd=root)
    cli._push(root, app.repo.clone_url(write=True, ttl_s=600), LIVE_BRANCH)
    out.note(f"Pushed {sha[:7]} to {LIVE_BRANCH}: it shows in the session's pages now.")
    return 0


def cmd_live_end(args: argparse.Namespace) -> int:
    app = _app(args)
    op = app.live.end(deploy=not args.no_deploy)
    if args.no_wait:
        out.value_last(op.id)
        out.note(f"Ending. Wait for it with: noclick wait {op.id}")
        return 0
    out.note("Building, checking and deploying what was edited…" if not args.no_deploy else "Stopping…")
    ended = op.wait(timeout=args.timeout)
    if args.json:
        out.print_json(ended)
        return 0
    said = {"deployed": "Deployed: production serves what was edited.", "no_changes": "Nothing was edited.",
            "stopped": "Stopped without deploying.", "aborted": "An edit came in as it ended: it's live again."}
    out.note(said.get(ended.outcome, ended.outcome))
    if ended.main_behind:
        out.note("Production's branch couldn't move to it yet: the next session's start merges it.")
    if ended.deployment_id:
        out.value_last(Deployment.from_id(ended.deployment_id).url)
    return 0


def _start_flags(parser: argparse.ArgumentParser, *, json_flag: bool = True) -> None:
    parser.add_argument("--hours", type=float, default=1.0, help="End it after this long at most (default 1).")
    spend.add_flag(parser, what="the session")
    parser.add_argument("--timeout", type=float, default=START_TIMEOUT_S, metavar="SECONDS",
                        help=f"How long to wait for it to start (default {START_TIMEOUT_S:.0f}).")
    if json_flag:
        parser.add_argument("--json", action="store_true", help="Print the session as JSON.")


def register(kit: Any) -> None:
    live = kit.commands.add_parser(
        "live", help="Edit the app live: a dev server with its real bindings, then ship what was edited.",
        description=__doc__)
    # Plain `noclick live` starts the session, taking start's flags.
    live.set_defaults(run=cmd_live_start, auth=True, project=None, user=None)
    _start_flags(live)
    steps = live.add_subparsers(dest="live_command", metavar="<step>")

    def step(name: str, run: Any, summary: str) -> argparse.ArgumentParser:
        sub = kit.command(steps, name, run, summary, parents=[kit.as_json, kit.user])
        sub.add_argument("project", nargs="?", help="The app (default: the folder's linked one).")
        sub.add_argument("--app", help="The app, as a flag: the same as the argument.")
        return sub

    _start_flags(step("start", cmd_live_start, "Start the session (what plain noclick live does) and print its link."),
                 json_flag=False)
    step("status", cmd_live_status, "The session's state, edits and branch.")
    step("push", cmd_live_push, f"Push the commit you're on to {LIVE_BRANCH}: it shows in the session at once.")
    end = step("end", cmd_live_end, "End it: build, check and deploy what was edited (production stays on a failure).")
    end.add_argument("--no-deploy", action="store_true", help="Stop it without deploying.")
    end.add_argument("--no-wait", action="store_true", help="Print the operation id instead of waiting.")
    end.add_argument("--timeout", type=float, metavar="SECONDS", help="Give up waiting after this long (exit 124).")
