"""Boot-time git mounts for agent sandboxes.

Providers wired into an agent's bottom handle can request sandbox
environment (``agent_sandbox_repo`` on a GitHub provider → an
authenticated clone). The setups are resolved backend-side by
``AgentNode._resolve_sandbox_mounts`` (credential → token, never through
the model) and applied here when the local runtime starts.

Multiple mounts (several provider nodes on one agent) land side by side
in the workdir. Directory names dedupe (name → owner-name on collision),
and credentials are stored per repo URL (``credential.useHttpPath``) so
mounts from different accounts on the same host can't clobber each
other's tokens. Git identity is per-repo local config for the same
reason.

Without a FilesystemNode the clone lands on the sandbox's ephemeral disk
and is wiped when the sandbox dies — push it or lose it. With one, the
workdir is the persistent volume and the clone survives (clone-if-missing).

Subprocess calls are awaited directly so they never block the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def assign_mount_dirs(setups: List[Dict[str, Any]]) -> None:
    """Assign a unique ``dir`` to each setup (in place).

    First claimant of a repo name gets the bare name; collisions fall back
    to ``owner-name`` (and a numeric suffix in the degenerate same-repo-twice
    case, which clone-if-missing would otherwise silently alias).
    """
    taken: set = set()
    for setup in setups:
        owner, name = setup["repo"].split("/", 1)
        candidates = [name, f"{owner}-{name}"]
        chosen = None
        for candidate in candidates:
            if candidate not in taken:
                chosen = candidate
                break
        if chosen is None:
            n = 2
            while f"{owner}-{name}-{n}" in taken:
                n += 1
            chosen = f"{owner}-{name}-{n}"
        taken.add(chosen)
        setup["dir"] = chosen


def build_git_mount_script(setup: Dict[str, Any], workdir: str) -> str:
    """Shell script that authenticates git and clones one repo.

    The token lands in ~/.git-credentials keyed by the FULL repo URL
    (``credential.useHttpPath true``) — per-repo matching, so two mounts
    from different accounts on the same host each push with their own
    token. The agent runs arbitrary bash in this sandbox, so it can read
    the token either way; this just makes plain ``git push`` work. The
    credentials file is rewritten per repo on every boot (it lives in the
    container home, not the volume) so refreshed tokens always apply.
    Clone is skipped when the target already contains a git repo
    (persistent-volume case); git identity is the repo's LOCAL config —
    it persists with the volume and never cross-contaminates other mounts.
    """
    host = setup["host"]
    repo_path = f"{host}/{setup['repo']}"
    cred_line = f"https://x-access-token:{setup['token']}@{repo_path}.git"
    target = f"{workdir.rstrip('/')}/{setup['dir']}"
    clone_args = f"--branch {shlex.quote(setup['branch'])} " if setup.get("branch") else ""
    return (
        "set -e\n"
        f"mkdir -p {shlex.quote(workdir)}\n"
        "git config --global credential.helper store\n"
        "git config --global credential.useHttpPath true\n"
        f"touch ~/.git-credentials && chmod 600 ~/.git-credentials\n"
        # Replace any prior line for this exact repo, keep other repos' lines.
        f"grep -vF {shlex.quote('@' + repo_path + '.git')} ~/.git-credentials > ~/.git-credentials.tmp || true\n"
        f"printf '%s\\n' {shlex.quote(cred_line)} >> ~/.git-credentials.tmp\n"
        "mv ~/.git-credentials.tmp ~/.git-credentials\n"
        f"if [ ! -d {shlex.quote(target)}/.git ]; then\n"
        f"  git clone {clone_args}{shlex.quote(setup['clone_url'])} {shlex.quote(target)}\n"
        "fi\n"
        f"git -C {shlex.quote(target)} config user.name {shlex.quote(setup['git_user'])}\n"
        f"git -C {shlex.quote(target)} config user.email {shlex.quote(setup['git_email'])}\n"
    )


def build_gh_auth_script(setups: List[Dict[str, Any]]) -> str:
    """Shell script that authenticates the ``gh`` CLI via ~/.config/gh/hosts.yml.

    gh holds ONE token per host, so the first setup per host wins (same
    ordering as the mounts themselves). Written fresh every boot — the
    config dir lives in the container home, not the volume.
    """
    hosts: Dict[str, Dict[str, Any]] = {}
    for setup in setups:
        hosts.setdefault(setup["host"], setup)
    yaml_lines: List[str] = []
    for host, setup in hosts.items():
        yaml_lines.extend([
            f"{host}:",
            f"    oauth_token: {setup['token']}",
            f"    user: {setup['git_user']}",
            "    git_protocol: https",
        ])
    printf_args = " ".join(shlex.quote(line) for line in yaml_lines)
    return (
        "set -e\n"
        "mkdir -p ~/.config/gh\n"
        f"printf '%s\\n' {printf_args} > ~/.config/gh/hosts.yml\n"
        "chmod 600 ~/.config/gh/hosts.yml\n"
    )


def describe_git_mounts(setups: List[Dict[str, Any]], workdir: str) -> str:
    """One-paragraph note telling the model where the repos are and how to land
    work upstream. Persistence is described by the workspace note; the clone lives
    under that workspace, so stating it here too could contradict it."""
    if not setups:
        return ""
    assign_mount_dirs(setups)
    lines = []
    for setup in setups:
        path = f"{workdir.rstrip('/')}/{setup['dir']}"
        lines.append(
            f"Repository {setup['repo']} is cloned at {path} with authenticated "
            f"git (you can push branches)."
        )
    lines.append(
        "Both git and the gh CLI are authenticated for these hosts. To open a PR, "
        "prefer a provider tool like github__create_pull_request when it is in your "
        "tool list; otherwise use gh (e.g. gh pr create). Commit and push work you "
        "want to land upstream."
    )
    return " ".join(lines)

async def apply_git_mounts_local(setups: List[Dict[str, Any]], workdir: str) -> None:
    """Run the same mount bootstrap on the local machine (self-hosted sandbox).

    Identical scripts, executed via subprocess instead of a sandbox handle.
    Raises on the first failed setup, same as the handle-based applier.
    """
    assign_mount_dirs(setups)
    for setup in setups:
        await _run_local(build_git_mount_script(setup, workdir), f"Local mount of {setup['repo']}")
        logger.info("[sandbox-git] mounted %s at %s/%s (local)",
                    setup["repo"], workdir.rstrip("/"), setup["dir"])
    await _run_local(build_gh_auth_script(setups), "gh CLI auth")


async def _run_local(script: str, what: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "sh", "-c", script,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await process.communicate()
    if process.returncode != 0:
        detail = (stderr_b or stdout_b).decode(errors="replace")[-500:]
        raise RuntimeError(f"{what} failed (exit {process.returncode}): {detail}")
