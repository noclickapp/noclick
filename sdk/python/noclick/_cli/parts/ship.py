"""Ship and configure an app from a folder: ``deploy``, ``link``, ``status``, ``open``, ``releases``, ``rollback``,
``promote``, ``delete``, ``secret``, ``env``, ``bind`` and ``domains add|ls``.

A command that acts on an app takes it from ``--app`` (a name or an id), else from the folder's link
(``.noclick/project.json``, which ``noclick link`` and a folder's first deploy write). Progress goes to stderr; stdout
holds the one value worth keeping (a URL, an id), on its own last line, or with ``--json`` the whole answer.
"""

from __future__ import annotations

import argparse
import fnmatch
import getpass
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ... import cli as _cli
from ..._object import UNSET
from ..._sync import run_sync
from ...bucket import Bucket
from ...database import Database
from ...dicts import Dict as NcDict
from ...exceptions import Conflict, Error, NotFound, OperationFailed
from ...project import Deployment, Project
from ...queues import Queue
from ...repo import Repo, _blob_sha
from .. import appconfig, link as links, output

CommandError = _cli.CommandError
_note = output.note

_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_KINDS: Dict[str, Callable[..., Any]] = {"database": Database, "bucket": Bucket, "dict": NcDict, "queue": Queue}
# What `bind` calls each kind.
_BIND_KINDS = {"db": "database", "database": "database", "bucket": "bucket", "dict": "dict", "queue": "queue",
               "objects": "objects"}
# How many of a list a command shows before it says how to see the rest (and ``--json``, how many files it names).
_SHOWN, _JSON_FILES = 20, 200


def _out(args: argparse.Namespace, data: Dict[str, Any], last: Optional[str]) -> None:
    """The command's answer on stdout: all of it as JSON with ``--json``, else its one value worth keeping."""
    if getattr(args, "json", False):
        output.print_json(data)
    else:
        output.value_last(last)


def _listed(items: Sequence[str], limit: int = _SHOWN) -> List[str]:
    shown = [f"  {item}" for item in items[:limit]]
    if len(items) > limit:
        shown.append(f"  … and {len(items) - limit} more")
    return shown


# --- which app ---------------------------------------------------------------------------------------------------


def _link_of(folder: Optional[Path] = None) -> Optional[links.Link]:
    try:
        return links.find(folder)
    except (ValueError, KeyError, TypeError):
        raise CommandError(f"The folder's {links.FOLDER}/{links.FILE} doesn't say which app it's linked to.",
                           next_step="noclick link <app> writes it again, or noclick unlink removes it.") from None


def _root(link: links.Link) -> Path:
    """The folder ``link`` ties to its app."""
    return link.path.parent.parent


def _lookup(ref: str) -> Project:
    """The app ``ref`` names (its id, or its name), loaded."""
    project = Project.from_id(ref) if _ID.match(ref) else Project.from_name(ref)
    project.production_branch  # loads it (a name or id given is only a hint), so a missing one says so here
    _cli._CONTEXT["app"] = project.name  # what an error's next step names
    return project


def _app(args: argparse.Namespace, folder: Optional[Path] = None) -> Tuple[Project, Optional[links.Link]]:
    """The app a command acts on: ``--app``, else the folder's link."""
    named = getattr(args, "app", None)
    if named:
        return _lookup(named), None
    link = _link_of(folder)
    if link is None:
        raise links.NotLinked("This folder isn't linked to an app.",
                              next_step="noclick link <app> (once per folder), or pass --app <app>.")
    try:
        return _lookup(link.app_id or link.app), link
    except NotFound:
        raise NotFound(f"{link.path} links this folder to {link.app}, which this key doesn't reach (deleted, or "
                       "another account's).",
                       next_step="noclick link <app> to link another, or noclick unlink.") from None


def _api_url(args: argparse.Namespace) -> str:
    return _cli.resolve_credentials(args.profile).api_url


# --- link -----------------------------------------------------------------------------------------------------


def cmd_link(args: argparse.Namespace) -> int:
    folder = Path(args.dir or os.getcwd()).resolve()
    ref = args.app_ref or args.app
    if ref is None:
        raise CommandError("Name the app to link this folder to.", next_step="noclick link <app> (its name or id).")
    try:
        project = _lookup(ref)
    except NotFound:
        if not args.create:
            raise NotFound(f"No app is named {ref!r}.",
                           next_step=f"noclick link {ref} --create makes it (and its repo), or noclick deploy does "
                                     "on the folder's first deploy.") from None
        project = _create(ref, args.budget)
        _note(f"Made the app {project.name} and its repo.")
    link = links.write(project.name, app_id=project.id, api_url=_api_url(args), root=folder)
    _note(f"Linked {folder} to {project.name}.")
    _out(args, {"app": {"id": project.id, "name": project.name, "url": project.url}, "link": str(link.path)},
         project.url)
    return 0


def cmd_unlink(args: argparse.Namespace) -> int:
    link = _link_of(Path(args.dir or os.getcwd()))
    if link is None:
        raise CommandError("This folder isn't linked to an app.", next_step="Nothing to undo.")
    links.remove(_root(link))
    _note(f"Unlinked {_root(link)} from {link.app}. The app itself is unchanged.")
    _out(args, {"unlinked": str(_root(link)), "app": {"id": link.app_id, "name": link.app}}, None)
    return 0


def _create(name: str, budget: Optional[float]) -> Project:
    repo = Repo.from_name(name, create_if_missing=True)
    project = Project.from_name(name, repo=repo, create_if_missing=True,
                                budget_usd_per_month=UNSET if budget is None else budget)
    project.id  # make it now
    return project


def _app_name(folder: Path) -> str:
    """An app's name from a folder's (``My Site`` → ``my-site``)."""
    name = re.sub(r"[^a-z0-9]+", "-", folder.name.lower()).strip("-")
    return name[:63] or "app"


# --- what a folder is -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """What a folder holds, as a deploy will build it: its ``kind``, in words (``said``), and on which ``runtime``."""

    kind: str
    said: str
    runtime: str


_PYTHON = ("requirements.txt", "pyproject.toml", "Pipfile")
_SERVER_SOURCE = (".py", ".rb", ".php", ".go", ".java", ".rs", ".cs", ".ex", ".exs", ".pl", ".kt", ".scala")
_SERVER_SCRIPTS = ("server.js", "server.mjs", "server.ts", "server.cjs")


def _package(folder: Path) -> Dict[str, Any]:
    path = folder / "package.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        raise CommandError("package.json isn't valid JSON.", next_step="Fix package.json, then deploy again.") \
            from None
    return data if isinstance(data, dict) else {}


def detect_shape(folder: Path) -> Shape:
    """What ``folder`` (the app's own) holds, read as NoClick's build reads it; the build has the final word."""
    package = _package(folder)
    deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})}
    scripts = package.get("scripts") or {}
    wrangler = appconfig.find_wrangler(folder)
    if (folder / "Dockerfile").is_file():
        return Shape("docker", "a container (its Dockerfile)", "container")
    if wrangler is not None and wrangler.suffix != ".toml":
        try:
            main = appconfig.read_wrangler(wrangler).get("main")
        except appconfig.ConfigError:
            main = None
        if main:
            return Shape("worker", f"a Worker ({wrangler.name} runs {main})", "edge")
    for dep, said in (("next", "a Next.js app"), ("astro", "an Astro site"),
                      ("@react-router/dev", "a React Router app"), ("@remix-run/dev", "a Remix app"),
                      ("vite", "a Vite site")):
        if dep in deps:
            return Shape(dep.rsplit("/", 1)[0].lstrip("@"), said, "edge")
    if any((folder / name).is_file() for name in _PYTHON):
        return Shape("python", "a Python server (a container)", "container")
    if package and scripts.get("start") and not scripts.get("build"):
        return Shape("node", "a Node server (a container)", "container")
    if package and scripts.get("build"):
        return Shape("build", "a site its build script makes", "edge")
    if (folder / "index.html").is_file() or (folder / "public" / "index.html").is_file():
        return Shape("files", "a site of files", "edge")
    return Shape("unknown", "what NoClick's build finds in it", "auto")


def _source_published(shape: Shape, paths: Sequence[str]) -> List[str]:
    """The server code a site of files would publish as files anyone can download."""
    if shape.kind != "files":
        return []
    return [p for p in paths if p.endswith(_SERVER_SOURCE) or p.rsplit("/", 1)[-1] in _SERVER_SCRIPTS]


# --- secrets kept out of a deploy -----------------------------------------------------------------------------

_TEMPLATES = (".example", ".sample", ".template", ".dist", ".defaults")
_SECRET_FILES = (".netrc", ".git-credentials", "id_rsa", "id_ed25519", "id_ecdsa", "credentials.json")
_SECRET_FOLDERS = (".ssh", ".aws", ".gnupg")
_PRIVATE_KEY = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_TOKEN_LINE = re.compile(rb"(_authToken|npmAuthToken|_auth|_password)\s*[=:]\s*(?![\"']?\$\{)\S")


def _secret_file(root: Path, path: str) -> bool:
    """Whether ``path`` holds a secret: by its name (``.env``, ``.dev.vars``, a key, a login), or by what it holds
    (a private key; a package manager's settings with a token written in)."""
    parts = path.split("/")
    name = parts[-1].lower()
    if any(part.lower() in _SECRET_FOLDERS for part in parts[:-1]):
        return True
    if name.startswith((".env", ".dev.vars")) and not name.endswith(_TEMPLATES):
        return True
    if name in _SECRET_FILES or name.startswith("service-account") and name.endswith(".json"):
        return True
    if name.endswith((".pem", ".key", ".p12", ".pfx")) or name in (".npmrc", ".yarnrc", ".yarnrc.yml"):
        try:
            head = (root / path).read_bytes()[:65536]
        except OSError:
            return False
        if name.endswith((".p12", ".pfx")):
            return True
        return bool(_PRIVATE_KEY.search(head) if name.endswith((".pem", ".key")) else _TOKEN_LINE.search(head))
    return False


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", re.M)


@dataclass(frozen=True)
class LeftOut:
    """A file a deploy left out because it looks like a secret, and the names it gives values to (an env file's;
    never a value)."""

    path: str
    names: Tuple[str, ...] = ()

    def next_steps(self) -> List[str]:
        if self.names:
            return [f"noclick secret set {name} --from-env {name}" for name in self.names]
        return [f"noclick secret set NAME --stdin < {self.path}"]

    def as_data(self) -> Dict[str, Any]:
        return {"path": self.path, "why": "looks like a secret, and a secret never ships in the app's code",
                "names": list(self.names), "next_steps": self.next_steps()}


def _left_out(root: Path, path: str) -> LeftOut:
    name = path.rsplit("/", 1)[-1].lower()
    names: Tuple[str, ...] = ()
    if name.startswith((".env", ".dev.vars")):
        try:
            text = (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        names = tuple(dict.fromkeys(_ENV_LINE.findall(text)))
    return LeftOut(path, names)


def keep_secrets_out(root: Path, paths: Sequence[str], committed: Sequence[str] = (),
                     head: Optional[str] = None) -> List[LeftOut]:
    """The files of ``paths`` a deploy leaves out because they look like secrets. One already committed in ``head``
    (``committed``: its files), the commit a deploy ships, refuses it: that's in the app's history either way."""
    in_history = [p for p in committed if _secret_file(root, p)]
    if in_history:
        raise CommandError(
            f"{', '.join(in_history[:5])}" + (f" and {len(in_history) - 5} more" if len(in_history) > 5 else "")
            + f" looks like a secret and is committed in {(head or '')[:7]}, the commit this deploy ships, so "
            "deploying would put it in the app's repo.",
            next_step=f"git rm --cached {' '.join(in_history[:5])}, add it to .gitignore and commit; give the app "
                      "each value with noclick secret set NAME --from-env NAME, and change the values (they're in "
                      "this checkout's history).",
            details={"files": in_history})
    return [_left_out(root, p) for p in paths if _secret_file(root, p)]


def say_left_out(left: Sequence[LeftOut]) -> None:
    for item in left:
        _note(f"Left out {item.path}: it looks like a secret, and a secret never ships in the app's code. Give the "
              "app its values with:")
        for step in item.next_steps():
            _note(f"  {step}")


# --- shipping a git checkout ----------------------------------------------------------------------------------

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_SNAPSHOT = re.compile(r"^NoClick-Snapshot-Of: (\S+)$", re.M)


def _git(*args: str, cwd: str, env: Optional[Dict[str, str]] = None) -> str:
    return _cli._git(*args, cwd=cwd, env=env)


def _git_yes(*args: str, cwd: str, env: Optional[Dict[str, str]] = None) -> bool:
    """Whether a git question (``merge-base --is-ancestor``, ``cat-file -e``) answers yes."""
    try:
        _git(*args, cwd=cwd, env=env)
    except CommandError as err:
        if "stderr" not in err.details:
            raise
        return False
    return True


def git_root(folder: Path) -> Optional[str]:
    """The checkout ``folder`` is in; None outside one (or without git)."""
    try:
        return _git("rev-parse", "--show-toplevel", cwd=str(folder))
    except CommandError:
        return None


@dataclass
class Tree:
    """A checkout's working tree as git would commit it: its ``tree``, the commit it's on (``head``, None before the
    first) and what it changes from there (``changes``: ``(status, path)``, A, M or D)."""

    tree: str
    head: Optional[str]
    head_tree: str
    changes: List[Tuple[str, str]] = field(default_factory=list)
    left_out: List[LeftOut] = field(default_factory=list)


def working_tree(root: str) -> Tree:
    """The checkout's files as they are, ignored ones and uncommitted ones that look like secrets left out, without
    touching its index, HEAD or branch. A secret committed in HEAD refuses (``keep_secrets_out``)."""
    try:
        head: Optional[str] = _git("rev-parse", "--verify", "--quiet", "HEAD^{commit}", cwd=root)
    except CommandError:
        head = None
    index = Path(root) / _git("rev-parse", "--git-path", "index", cwd=root)
    with tempfile.TemporaryDirectory() as tmp:
        scratch = os.path.join(tmp, "index")
        if index.is_file():
            # Its times kept: git trusts a file's size and time only where they're older than the index's own, so a
            # copy newer than the checkout's index would take a file changed within that second for unchanged.
            shutil.copy2(index, scratch)
        env = {"GIT_INDEX_FILE": scratch}
        _git("add", "-A", "--", ".", ":(exclude).noclick", cwd=root, env=env)
        base = head or EMPTY_TREE
        committed = _git("ls-tree", "-r", "-z", "--name-only", head, cwd=root).split("\0") if head else []
        added = _git("diff", "--cached", "--name-only", "--no-renames", "--diff-filter=AM", "-z", base, cwd=root,
                     env=env).split("\0")
        left = keep_secrets_out(Path(root), [p for p in added if p], [p for p in committed if p], head)
        if left:
            _git("rm", "--cached", "--quiet", "--", *(item.path for item in left), cwd=root, env=env)
        tree = _git("write-tree", cwd=root, env=env)
        listed = _git("diff", "--cached", "--name-status", "--no-renames", "-z", base, cwd=root, env=env).split("\0")
    head_tree = _git("rev-parse", f"{head}^{{tree}}", cwd=root) if head else EMPTY_TREE
    return Tree(tree, head, head_tree, [(status[0], path) for status, path in zip(listed[::2], listed[1::2]) if path],
                left)


def _identity(root: str) -> Dict[str, str]:
    """Who a snapshot commit is by: git's own setting, else this machine's user."""
    env: Dict[str, str] = {}
    for key, var in (("user.name", "NAME"), ("user.email", "EMAIL")):
        try:
            _git("config", key, cwd=root)
        except CommandError:
            who = getpass.getuser() if var == "NAME" else f"{getpass.getuser()}@{socket.gethostname()}"
            env.update({f"GIT_AUTHOR_{var}": who, f"GIT_COMMITTER_{var}": who})
    return env


@dataclass
class Shipped:
    """What a deploy shipped: the ``commit``, its ``branch``, and, for a snapshot, the files it carried."""

    commit: Optional[str]
    branch: str
    snapshot: bool = False
    files: List[Tuple[str, str]] = field(default_factory=list)
    replaced: Optional[str] = None
    left_out: List[LeftOut] = field(default_factory=list)


def check_tree(root: str, tree: Tree, *, only_committed: bool) -> None:
    """Refuse a checkout with nothing to deploy, or uncommitted work under ``--only-committed``."""
    dirty = tree.tree != tree.head_tree
    if dirty and only_committed:
        raise CommandError(
            f"Your checkout has uncommitted changes ({len(tree.changes)} files), and --only-committed ships commits "
            "alone.", next_step="Commit them, or deploy without --only-committed to ship the folder as it is.",
            details={"files": [p for _, p in tree.changes]})
    if tree.tree == EMPTY_TREE:
        raise CommandError("There's nothing to deploy: the folder holds no files git would commit.",
                           next_step="Add the app's files (or check .gitignore), then deploy again.")


def ship_checkout(root: str, tree: Tree, url: str, branch: str, *, message: str) -> Shipped:
    """Push the checkout to the app's repo as ``branch``: the commit it's on, or, with uncommitted or untracked
    files, a snapshot of its working ``tree`` as a commit of its own on top. The checkout itself never changes. The
    app's branch holding an earlier snapshot of this checkout is moved on from it; one holding commits the checkout
    doesn't have refuses (``noclick.Conflict``), fetched as ``noclick/<branch>`` to merge."""
    dirty = tree.tree != tree.head_tree
    env = _cli._repo_remote(url)
    remote = _git("ls-remote", "noclick-deploy", f"refs/heads/{branch}", cwd=root, env=env).split()
    remote_head = remote[0] if remote else None
    parents = [tree.head] if tree.head else []
    replaced = None
    if remote_head and remote_head != tree.head and not (tree.head and _ancestor(root, env, branch, remote_head,
                                                                                    tree.head)):
        if not _git_yes("cat-file", "-e", f"{remote_head}^{{commit}}", cwd=root):
            _fetch(root, env, branch)
        base = _snapshot_base(root, remote_head)
        if base is None or not (base == "none" or tree.head and (base == tree.head or _git_yes(
                "merge-base", "--is-ancestor", base, tree.head, cwd=root))):
            raise Conflict(
                f"The app's {branch} has commits this checkout doesn't (an app service can commit code, too).",
                next_step=f"They're fetched as noclick/{branch}: git merge noclick/{branch}, then deploy again.")
        parents.append(remote_head)  # an earlier snapshot of this checkout: this one takes its place
        replaced = remote_head
    if not dirty and not replaced:
        sha = tree.head
    else:
        said = [f"{s} {p}" for s, p in tree.changes[:50]] + ([f"… and {len(tree.changes) - 50} more"]
                                                             if len(tree.changes) > 50 else [])
        body = f"{message}\n\n" + ("\n".join(said) + "\n\n" if said else "") + \
            f"NoClick-Snapshot-Of: {tree.head or 'none'}\n"
        args = ["commit-tree", tree.tree]
        for parent in parents:
            args += ["-p", parent]
        sha = _git(*args, "-m", body, cwd=root, env=_identity(root))
    _push(root, env, sha, branch)
    return Shipped(sha, branch, snapshot=sha != tree.head, files=tree.changes if dirty else [], replaced=replaced,
                   left_out=tree.left_out)


def _ancestor(root: str, env: Dict[str, str], branch: str, sha: str, of: str) -> bool:
    """Whether the app's head ``sha`` is in ``of``'s history, fetching it first when the checkout lacks it."""
    if not _git_yes("cat-file", "-e", f"{sha}^{{commit}}", cwd=root):
        _fetch(root, env, branch)
    return _git_yes("merge-base", "--is-ancestor", sha, of, cwd=root)


def _fetch(root: str, env: Dict[str, str], branch: str) -> None:
    _git("fetch", "--quiet", "noclick-deploy", f"+refs/heads/{branch}:refs/remotes/noclick/{branch}", cwd=root,
         env=env)


def _snapshot_base(root: str, sha: str) -> Optional[str]:
    """The commit a snapshot ``sha`` was taken on (``none`` before the first); None when it isn't a snapshot."""
    found = _SNAPSHOT.search(_git("log", "-1", "--format=%B", sha, cwd=root))
    return found.group(1) if found else None


def _push(root: str, env: Dict[str, str], sha: str, branch: str) -> None:
    try:
        _git("push", "--quiet", "noclick-deploy", f"{sha}:refs/heads/{branch}", cwd=root, env=env)
    except CommandError as err:
        stderr = err.details.get("stderr") or ""
        if "Operation too slow" in stderr:
            raise CommandError(f"The repo's git endpoint sent nothing for {_cli.GIT_GIVE_UP_S} seconds, so the push "
                               "gave up.", next_step="noclick deploy again.", details=err.details) from None
        if "[rejected]" not in stderr:
            raise
        _fetch(root, env, branch)
        raise Conflict(
            f"The app's {branch} moved on while this deploy pushed (an app service can commit code, too).",
            next_step=f"It's fetched as noclick/{branch}: git merge noclick/{branch}, then deploy again.",
        ) from None


# --- shipping a folder that isn't a checkout ------------------------------------------------------------------

# What a folder outside git leaves out on its own (a checkout's .gitignore decides there).
DEFAULT_EXCLUDES = (".git", ".noclick", "node_modules", ".venv", "venv", "__pycache__", ".DS_Store", ".wrangler",
                    ".next", ".turbo", ".cache", ".vercel", ".netlify", "*.pyc")
# What one commit through the API carries (``Repo.commit``).
MAX_FILES, MAX_BYTES = 1000, 50 * 1024 * 1024


def ignore_globs(root: Path) -> List[str]:
    """What a folder outside git leaves out: ``DEFAULT_EXCLUDES``, and its own ``.gitignore``'s patterns."""
    globs: List[str] = []
    lines = (root / ".gitignore").read_text().splitlines() if (root / ".gitignore").is_file() else []
    for line in [*DEFAULT_EXCLUDES, *lines]:
        pattern = line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if pattern.startswith("!"):
            raise CommandError(
                f".gitignore keeps {pattern[1:]} back in ({pattern}), which a folder outside git can't honour.",
                next_step="Run git init here (deploy then reads .gitignore as git does), or remove that line.")
        anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
        pattern = pattern.strip("/")
        globs += [pattern] if anchored else [pattern, f"*/{pattern}"]
    return globs


def _excluded(path: str, globs: Sequence[str]) -> bool:
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return any(fnmatch.fnmatchcase(p, glob) for glob in globs for p in prefixes)


def folder_files(root: Path, globs: Optional[Sequence[str]] = None) -> Dict[str, Path]:
    """The files a deploy of ``root`` carries, by their path from it; a link leading out of the folder is refused
    (what it leads to is this machine's, never the app's)."""
    globs = ignore_globs(root) if globs is None else globs
    top = root.resolve()
    found: Dict[str, Path] = {}
    for directory, subdirs, names in os.walk(root):
        here = Path(directory)
        subdirs[:] = sorted(d for d in subdirs if not _excluded((here / d).relative_to(root).as_posix(), globs))
        for name in sorted([*names, *(d for d in subdirs if (here / d).is_symlink())]):
            file = here / name
            path = file.relative_to(root).as_posix()
            if _excluded(path, globs):
                continue
            if file.is_symlink() and top not in (target := file.resolve()).parents:
                raise CommandError(f"The folder has a link, {path}, to {target}, outside it.",
                                   next_step="Put what it points to in the folder in its place (or .gitignore the "
                                             "link), then deploy again.")
            if file.is_file():
                found[path] = file
    return found


def ship_folder(root: Path, repo: Repo, branch: str, *, message: str) -> Shipped:
    """Make ``branch`` of the app's repo hold the folder's files as one commit through the API, sending only what
    changed; no git needed."""
    globs = ignore_globs(root)
    local = folder_files(root, globs)
    left = keep_secrets_out(root, list(local))
    for item in left:
        del local[item.path]
    if not local:
        raise CommandError(f"There's nothing to deploy: {root} holds no files.",
                           next_step="Run noclick deploy in the app's folder (or pass --dir).")
    branches = {b.name: b for b in repo.branches()}
    ref = branch if branch in branches else None
    remote = {f.path: f.sha for f in repo.files("", ref=ref, recursive=True) if f.type == "file"} if branches else {}
    changes: Dict[str, Optional[bytes]] = {}
    statuses: List[Tuple[str, str]] = []
    for path, file in local.items():
        data = file.read_bytes()
        if remote.get(path) != _blob_sha(data):
            changes[path] = data
            statuses.append(("M" if path in remote else "A", path))
    for path in remote:
        if path not in local and not _excluded(path, globs):
            changes[path] = None
            statuses.append(("D", path))
    size = sum(len(d) for d in changes.values() if d)
    if len(changes) > MAX_FILES or size > MAX_BYTES:
        raise CommandError(
            f"The folder changes {len(changes)} files ({output.size(size)}) since the last deploy, past the "
            f"{MAX_FILES} files and {MAX_BYTES // 2**20} MB one deploy of a folder outside git carries.",
            next_step="Leave out what the build makes (.gitignore it), or run git init and commit, then deploy "
                      "again: a checkout pushes with git, whatever its size.")
    if not changes:
        head = branches.get(branch)
        return Shipped(head.head if head else None, branch, left_out=left)
    commit = repo.commit(changes, message=message, branch=branch)
    return Shipped(commit.sha if commit else None, branch, snapshot=True, files=sorted(statuses, key=lambda s: s[1]),
                   left_out=left)


# --- deploy -------------------------------------------------------------------------------------------------------


def _branch(args: argparse.Namespace, project: Project, root: Optional[str]) -> str:
    """The branch a deploy ships to: ``--branch``, ``--preview``, ``--prod``, else the checkout's own (outside
    git, production)."""
    if args.branch:
        return args.branch
    if args.prod:
        return project.production_branch
    if args.preview is not None:
        if args.preview:
            return args.preview
        current = _current_branch(root) if root else None
        return current if current and current != project.production_branch else "preview"
    if root is None:
        return project.production_branch
    current = _current_branch(root)
    if current is None:
        raise CommandError("You're not on a branch.",
                           next_step="Pass --prod (the app's production branch), --preview, or --branch <name>.")
    return current


def _current_branch(root: str) -> Optional[str]:
    try:
        return _git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=root)
    except CommandError as err:
        if "stderr" not in err.details:
            raise
        return None


def _deploy_target(args: argparse.Namespace, root: Path, link: Optional[links.Link]) -> Tuple[Project, bool]:
    """The app a deploy ships to, and whether this deploy made it. Named, it must exist (or ``--create``); else the
    folder's link; else, for a folder with neither, a new app named after it (never an app it isn't tied to)."""
    if args.app_ref and args.app and args.app_ref != args.app:
        raise CommandError(f"Two apps named: {args.app_ref} and --app {args.app}.", next_step="Name the app once.")
    named = args.app_ref or args.app
    if named:
        try:
            return _lookup(named), False
        except NotFound:
            if not args.create:
                raise NotFound(f"No app is named {named!r}.",
                               next_step=f"noclick deploy --app {named} --create makes it (and its repo).") from None
            return _create(named, args.budget), True
    if link is not None:
        return _app(argparse.Namespace(app=None), _root(link))[0], False
    name = _app_name(root)
    try:
        existing = _lookup(name)
    except NotFound:
        return _create(name, args.budget), True
    raise CommandError(
        f"This folder isn't linked to an app, and you already have an app named {existing.name} ({existing.url}).",
        next_step=f"Deploy to it: noclick link {existing.name}, then noclick deploy. Or make a new one: noclick "
                  "deploy --app <new-name> --create.")


def cmd_deploy(args: argparse.Namespace) -> int:
    folder = Path(args.dir or os.getcwd()).resolve()
    if not folder.is_dir():
        raise CommandError(f"{folder} isn't a folder.", next_step="Pass --dir the app's folder.")
    link = _link_of(folder)
    checkout = None if args.no_git else git_root(folder)
    root = Path(checkout) if checkout else _root(link) if link else folder
    try:
        config = appconfig.read_config(root)
        app_folder = root / config.root if config.root else root
        translated = _translate(root, app_folder, config)
        if translated is not None:
            config = appconfig.parse(translated.config)
    except appconfig.ConfigError as bad:
        raise CommandError(bad.message, next_step=bad.next_step) from None
    shape = detect_shape(app_folder)
    # Everything a deploy refuses is refused before anything is made, set or pushed.
    if checkout:
        tree = working_tree(checkout)
        check_tree(checkout, tree, only_committed=args.only_committed)
        paths = _git("ls-tree", "-r", "--name-only", tree.tree, cwd=checkout).splitlines()
    else:
        if args.only_committed:
            raise CommandError(f"{root} isn't a git checkout, so there are no commits to ship.",
                               next_step="Deploy without --only-committed, which ships the folder as it is.")
        paths = [p for p in folder_files(root) if not _secret_file(root, p)]
    inside = config.root + "/" if config.root else ""
    published = _source_published(shape, [p[len(inside):] for p in paths if p.startswith(inside)])
    if published:
        raise _published_source(published)
    project, made = _deploy_target(args, root, link)
    if made:
        _note(f"Made the app {project.name} and its repo, with a monthly budget of "
              f"{output.usd(project.budget_usd_per_month)} (--budget sets another).")
    elif args.budget is not None:
        project.update(budget_usd_per_month=args.budget)
    branch = _branch(args, project, checkout)
    production = branch == project.production_branch
    _note(f"Deploying {root} to {project.name} ({'production' if production else 'a preview of ' + branch}): "
          f"{shape.said}.")
    applied = appconfig.Applied()
    if not config.empty and args.token:
        _note("A deploy token can't change the app's bindings, settings or schedules: the deploy checks those "
              "noclick.json names are in place, and says what's missing.")
    elif not config.empty:
        applied = appconfig.apply(project, config, classes=_KINDS)
    for change in applied.changes:
        _note(f"  {change}")
    message = f"Deploy {root.name} from {socket.gethostname()}"
    if checkout:
        shipped = ship_checkout(checkout, tree, project.repo.clone_url(write=True, ttl_s=600), branch,
                                message=message)
    else:
        shipped = ship_folder(root, project.repo, branch, message=message)
    _said_shipped(shipped)
    serving = None if made else project.production
    if serving is not None and serving.commit == shipped.commit and serving.branch == branch:
        _note(f"Production already serves {(shipped.commit or '')[:7]}: nothing changed since, so this builds it "
              "again.")
    if link is None and not args.app_ref and not args.app:
        written = links.write(project.name, app_id=project.id, api_url=_api_url(args), root=root)
        _note(f"Linked {root} to {project.name} ({written.path.relative_to(root)}): later commands here act on it.")
    op = project.deploy(branch=branch, commit=shipped.commit)
    data: Dict[str, Any] = {
        "app": {"id": project.id, "name": project.name}, "branch": branch, "production": production,
        "commit": shipped.commit, "operation_id": op.id, "shape": {"kind": shape.kind, "said": shape.said},
        "snapshot": shipped.snapshot, "files": [{"status": s, "path": p} for s, p in shipped.files[:_JSON_FILES]],
        "files_more": max(0, len(shipped.files) - _JSON_FILES), "configured": applied.changes,
        "made": applied.made, "translated": translated.added if translated else [],
        "left_out": [item.as_data() for item in shipped.left_out]}
    if args.no_wait:
        _note(f"Deploying. Wait for it with: noclick ops wait {op.id}")
        _out(args, data, op.id)
        return 0
    _note("Building…")
    try:
        deployment = op.wait(timeout=args.timeout)
    except OperationFailed as failed:
        deployment_id = failed.details.get("deployment_id")
        if deployment_id:  # its end, less a last line that's the error printed after it
            _cli._build_log(Deployment.from_id(deployment_id), last=20, leave_out=failed.message)
        raise
    if deployment.raw.get("preview_link"):
        _note(f"The preview is private: it opens with {deployment.raw['preview_link']}")
    broken = _cli._said_deployment(deployment.raw)
    where = "production" if deployment.production else "a preview of " + branch
    _note(f"Live, but not working: {where} stays deployed (nothing was rolled back)." if broken else
          f"Ready: {where}.")
    if not deployment.production:
        _note(f"Put it live in production with: noclick promote {branch}")
    data.update(url=deployment.url, deployment_id=deployment.id, status=deployment.status, ok=not broken,
                warning=deployment.raw.get("warning"), next_step=deployment.raw.get("next_step"),
                runtime_reason=deployment.raw.get("runtime_reason"))
    _out(args, data, deployment.url)
    return 1 if broken else 0


def _published_source(paths: Sequence[str]) -> CommandError:
    return CommandError(
        f"This folder is a site of files, so every file in it is published, and it holds server code: "
        f"{', '.join(paths[:5])}" + (f" and {len(paths) - 5} more" if len(paths) > 5 else "") + ".",
        next_step="Deploy only the site's own folder (noclick deploy --dir public), or run the code as a server "
                  "(a requirements.txt or Dockerfile beside it makes it one).", details={"files": list(paths)})


def _said_shipped(shipped: Shipped) -> None:
    say_left_out(shipped.left_out)
    short = (shipped.commit or "")[:7]
    if not shipped.snapshot:
        _note(f"Shipping {short or 'the branch as it is'} to {shipped.branch}.")
        return
    went = [f"{status} {path}" for status, path in shipped.files]
    _note(f"Shipping the folder as it is: {len(went)} file{'' if len(went) == 1 else 's'} beside the last commit, as "
          f"{short} on {shipped.branch} (your own checkout is unchanged)." if went else
          f"Shipping {short} to {shipped.branch}.")
    for line in _listed(went):
        _note(line)
    if shipped.replaced:
        _note(f"  (it takes the place of the earlier snapshot {shipped.replaced[:7]})")


def _translate(root: Path, app_folder: Path, config: appconfig.AppConfig) -> Optional[appconfig.Translation]:
    """A wrangler config's vars, D1, KV, R2, queues and crons into ``noclick.json``, saying what it added; refused
    while the wrangler config still names what NoClick's build won't take."""
    path = appconfig.find_wrangler(app_folder)
    if path is None:
        return None
    wrangler = appconfig.read_wrangler(path)
    done = appconfig.translate(wrangler, path.name, config.raw)
    if done.changed:
        appconfig.write_config(root, done.config)
        _note(f"{path.name} says what NoClick does its own way; noclick.json now has it:")
        for line in _listed(done.added):
            _note(line)
    for line in done.kept:
        _note(f"  kept {line}")
    if done.left:
        keys = sorted({key for key, _ in done.left})
        raise CommandError(
            f"{path.name} still names {', '.join(keys)}, which NoClick's build refuses (noclick.json now gives the "
            "app NoClick's own). In the code: " + "; ".join(how for _, how in done.left) + ".",
            next_step=f"Remove {', '.join(keys)} from {path.name}, make those changes, then noclick deploy again.",
            details={"keys": keys, "noclick_json": str(root / appconfig.NOCLICK_JSON)})
    return done if done.changed else None


# --- status, open, releases ---------------------------------------------------------------------------------------


def _gather(**reads: Callable[[], Any]) -> Dict[str, Any]:
    """Each read's answer, all at once, a failed one as its error (never the whole command's)."""
    import asyncio

    async def one(read: Callable[[], Any]) -> Any:
        try:
            return await read()
        except Error as err:
            return err

    async def every() -> List[Any]:
        return await asyncio.gather(*(one(read) for read in reads.values()))

    return dict(zip(reads, run_sync(every())))


def cmd_status(args: argparse.Namespace) -> int:
    _cli.note_unclaimed(args.profile)
    project, link = _app(args)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    reads = _gather(deployments=lambda: project.deployments.aio(limit=20),
                    bindings=lambda: project.bindings.aio(),
                    secrets=lambda: project.secrets.list.aio(),
                    settings=lambda: project.settings.list.aio(),
                    usage=lambda: project.usage.aio(),
                    errors=lambda: project.logs.aio(since=since, level="error", limit=5))
    production = project.production
    health = _gather(requests=lambda: production.requests.aio(since=since)) if production else {}
    deployments = reads["deployments"] if isinstance(reads["deployments"], list) else []
    previews: Dict[str, Deployment] = {}
    for d in deployments:
        if d.branch != project.production_branch and d.status == "ready" and d.branch not in previews:
            previews[d.branch] = d
    last = deployments[0] if deployments else None
    data: Dict[str, Any] = {
        "app": {"id": project.id, "name": project.name, "url": project.url, "runtime": project.runtime,
                "framework": project.framework, "production_branch": project.production_branch,
                "domains": project.domain_names, "linked_from": str(_root(link)) if link else None},
        "production": _deployment_view(production) if production else None,
        "previews": [_deployment_view(d) for d in previews.values()],
        "last_deploy": _deployment_view(last) if last else None,
    }
    lines = [f"{project.name}  {project.url}"]
    if project.domain_names:
        lines.append(f"  domains     {', '.join(project.domain_names)}")
    if production is not None:
        lines.append(f"  live        {_release_line(production)}")
    else:
        lines.append("  live        nothing yet: noclick deploy")
    outcomes = health.get("requests")
    if isinstance(outcomes, Error):
        lines.append(f"  health      unread ({outcomes.message})")
    elif outcomes is not None:
        rate = "-" if outcomes.error_rate is None else f"{outcomes.error_rate:.1%}"
        lines.append(f"  health      {outcomes.requests} requests in the last hour, {outcomes.errors} errors ({rate})")
        data["health"] = {"requests": outcomes.requests, "errors": outcomes.errors, "error_rate": outcomes.error_rate}
    if last is not None and (production is None or last.id != production.id):
        lines.append(f"  last deploy {_release_line(last)}")
    for d in previews.values():
        lines.append(f"  preview     {d.branch}: {d.url}")
    errors = reads["errors"]
    if isinstance(errors, Error):
        lines.append(f"  errors      unread ({errors.message})")
    else:
        data["recent_errors"] = [{"at": e.at, "message": e.message} for e in errors]
        if errors:
            lines.append(f"  errors      {len(errors)} in the last hour (noclick logs --level error); the latest:")
            lines += [f"              {appconfig.clip(errors[-1].message, 100)}"]
    for key, label, show in (("bindings", "bindings",
                              lambda bs: [f"{b.name} ({b.kind} {b.resource_name})" for b in bs]),
                             ("secrets", "secrets", sorted), ("settings", "env", sorted)):
        value = reads[key]
        if isinstance(value, Error):
            lines.append(f"  {label:<11} unread ({value.message})")
            continue
        names = show(value)
        data[key] = names
        lines.append(f"  {label:<11} {', '.join(names) if names else 'none'}")
    usage = reads["usage"]
    if isinstance(usage, Error):
        lines.append(f"  spend       unread ({usage.message})")
    else:
        budget = f" of its {output.usd(usage.budget_usd)} budget" if usage.budget_usd is not None else ""
        limited = f" (paid calls refused: {usage.limited_by}'s limit reached)" if usage.limited_by else ""
        lines.append(f"  spend       {output.usd(usage.usd)} this month{budget}{limited}")
        data["spend"] = {"usd": usage.usd, "budget_usd": usage.budget_usd, "limited_by": usage.limited_by}
    if getattr(args, "json", False):
        _out(args, data, None)
    else:
        print("\n".join(lines))
    return 0


def _release_line(d: Deployment) -> str:
    when = d.created_at.astimezone().strftime("%Y-%m-%d %H:%M") if isinstance(d.created_at, datetime) else "-"
    warning = f", but {d.raw['warning']}" if d.raw.get("warning") else ""
    return f"{d.status} {(d.commit or '')[:7]} on {d.branch}, {when}{warning}"


def _deployment_view(d: Deployment) -> Dict[str, Any]:
    return {"id": d.id, "branch": d.branch, "status": d.status, "commit": d.commit, "url": d.url,
            "production": d.production, "created_at": d.created_at, "warning": d.raw.get("warning")}


def cmd_open(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    url = project.url
    if args.preview is not None:
        branch = args.preview or None
        ready = [d for d in project.deployments(limit=50) if d.status == "ready" and not d.production
                 and (branch is None or d.branch == branch) and d.branch != project.production_branch]
        if not ready:
            raise NotFound(f"{project.name} has no preview{' of ' + branch if branch else ''} ready.",
                           next_step="noclick deploy --preview makes one.")
        url = ready[0].url
    if sys.stdout.isatty() and not args.no_browser:
        webbrowser.open(url)
    _out(args, {"url": url}, url)
    return 0


def cmd_releases(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    branch = None if args.all else project.production_branch
    found = project.deployments(branch=branch, limit=args.limit + 1)
    shown = found[: args.limit]
    if getattr(args, "json", False):
        _out(args, {"data": [_deployment_view(d) for d in shown], "has_more": len(found) > args.limit}, None)
        return 0
    output.table(("", "ID", "BRANCH", "STATUS", "COMMIT", "CREATED", "MESSAGE"),
                (["*" if d.production else "", d.id, d.branch, d.status, (d.commit or "")[:7], d.created_at,
                  appconfig.clip((d.commit_message or "").splitlines()[0] if d.commit_message else "", 50)]
                 for d in shown), empty=f"{project.name} has no deployments yet: noclick deploy.")
    if len(found) > args.limit:
        _note(f"More: noclick releases --limit {args.limit * 2}{' --all' if args.all else ''}")
    if shown:
        _note("* serves production. Go back to one: noclick rollback <id>")
    return 0


def _wait_release(args: argparse.Namespace, project: Project, op: Any, verb: str) -> int:
    if args.no_wait:
        _note(f"{verb}. Wait for it with: noclick ops wait {op.id}")
        _out(args, {"operation_id": op.id}, op.id)
        return 0
    deployment = op.wait(timeout=args.timeout)
    broken = _cli._said_deployment(deployment.raw)
    _note("Live, but not working: it stays live (go back with noclick rollback)." if broken else
          f"Live: {(deployment.commit or deployment.id)[:7]} serves production.")
    url = (deployment.raw.get("serves") or {}).get("production") or project.url
    _out(args, {"operation_id": op.id, **_deployment_view(deployment), "url": url, "ok": not broken}, url)
    return 1 if broken else 0


def cmd_rollback(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    releases = project.deployments(branch=project.production_branch, limit=20)
    if args.release:
        target = _find_release(releases, args.release)
        if target is None and _ID.match(args.release):
            target = Deployment.get(args.release)
        if target is None:
            raise NotFound(f"No release of {project.name} is {args.release}.",
                           next_step="noclick releases lists them by id and commit.")
    else:
        live = next((i for i, d in enumerate(releases) if d.production), None)
        earlier = [d for d in releases[(live + 1 if live is not None else 0):] if d.status == "ready"]
        if not earlier:
            raise NotFound(f"{project.name} has no earlier release to go back to.",
                           next_step="noclick releases lists what it has.")
        target = earlier[0]
    when = output.cell(target.created_at)
    _note(f"Rolling {project.name} back to {(target.commit or target.id)[:7]} ({when}).")
    return _wait_release(args, project, project.rollback(to=target), "Rolling back")


def _find_release(releases: Sequence[Deployment], ref: str) -> Optional[Deployment]:
    return next((d for d in releases if d.id == ref or (len(ref) >= 7 and (d.commit or "").startswith(ref))
                 or d.url == ref.rstrip("/")), None)


def cmd_promote(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    ref = args.preview
    if _ID.match(ref):
        target = Deployment.get(ref)
    else:
        ready = [d for d in project.deployments(limit=50) if d.status == "ready"]
        target = next((d for d in ready if d.branch == ref or d.url == ref.rstrip("/")), None) or \
            _find_release(ready, ref)
    if target is None:
        raise NotFound(f"{project.name} has no ready preview of {ref}.",
                       next_step=f"noclick deploy --preview {ref} makes one; noclick releases --all lists them.")
    _note(f"Promoting {target.branch} ({(target.commit or '')[:7]}) to production.")
    return _wait_release(args, project, target.promote(force=args.force), "Promoting")


# --- delete -------------------------------------------------------------------------------------------------------


def cmd_delete(args: argparse.Namespace) -> int:
    project, link = _app(args)
    preview = project.preview_delete(delete_data=args.delete_data)
    lines = [preview.deletes, *(f"  {line}" for line in preview.depends_on_it + preview.data_lost)]
    if preview.undo:
        lines.append(preview.undo)
    data = {"app": {"id": project.id, "name": project.name}, "preview": preview.raw, "deleted": False}
    if not args.yes:
        for line in lines:
            _note(line)
        command = f"noclick delete --app {project.name}{' --delete-data' if args.delete_data else ''} --yes"
        _note(f"Nothing was deleted. To delete it: {command}")
        _out(args, data, command)
        return 2
    item = project.delete(delete_data=args.delete_data)
    if link is not None and link.app_id in (project.id, None):
        links.remove(_root(link))
        _note(f"Unlinked {_root(link)}.")
    _note(f"Deleted {project.name}: {preview.undo or 'it can’t be undone.'}")
    data.update(deleted=True, trash_item_id=getattr(item, "id", None))
    _out(args, data, getattr(item, "id", None))
    return 0


# --- secrets and settings -----------------------------------------------------------------------------------------


def cmd_secret_set(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    if args.from_env:
        value = os.environ.get(args.from_env)
        if value is None:
            raise CommandError(f"{args.from_env} isn't set in this shell.",
                               next_step=f"export {args.from_env}=... first, or pipe it: noclick secret set "
                                         f"{args.name} --stdin.")
    else:
        if sys.stdin.isatty():
            raise CommandError("--stdin reads a value piped in, and stdin is a terminal.",
                               next_step=f"Pipe it: printf %s \"$VALUE\" | noclick secret set {args.name} --stdin, or "
                                         "pass --from-env VAR.")
        value = sys.stdin.read()
        value = value[:-1] if value.endswith("\n") else value
        value = value[:-1] if value.endswith("\r") else value
    if not value:
        raise CommandError("That value is empty.", next_step="Pass the value through --from-env or --stdin.")
    project.secrets.set(args.name, value, environment=args.env)
    where = {"all": "production and previews", "production": "production", "preview": "previews"}[args.env]
    _note(f"Set {args.name} for {where} on {project.name} ({len(value)} characters, never shown). It reaches the "
          "app at its next deploy: noclick deploy.")
    _out(args, {"name": args.name, "environment": args.env, "app": project.name}, None)
    return 0


def cmd_secret_ls(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    found = project.secrets.list(environment=args.env)
    if getattr(args, "json", False):
        _out(args, {"data": [{"name": n, "updated_at": at} for n, at in sorted(found.items())]}, None)
        return 0
    output.table(("NAME", "UPDATED"), sorted(found.items()), empty=f"{project.name} has no secrets for {args.env}.")
    return 0


def cmd_secret_rm(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    for name in args.names:
        project.secrets.delete(name, environment=args.env)
        _note(f"Deleted {name} from {project.name} ({args.env}); the app stops seeing it at its next deploy.")
    _out(args, {"deleted": args.names, "environment": args.env}, None)
    return 0


def _pair(text: str) -> Tuple[str, str]:
    name, sep, value = text.partition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"write each as KEY=value, not {text!r}")
    return name, value


def _config_beside(link: Optional[links.Link]) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """The linked folder's ``noclick.json``, when it has one."""
    if link is None or not (_root(link) / appconfig.NOCLICK_JSON).is_file():
        return None
    try:
        return _root(link), appconfig.read_json(_root(link) / appconfig.NOCLICK_JSON)
    except appconfig.ConfigError as bad:
        raise CommandError(bad.message, next_step=bad.next_step) from None


def _keep_in_step(link: Optional[links.Link], section: str, change: Callable[[Dict[str, Any]], bool]) -> None:
    """Change ``noclick.json``'s ``section`` the same way, where it names one: the next deploy gives the app what it
    says, so it would undo a change made only to the app."""
    found = _config_beside(link)
    if found is None or section not in found[1]:
        return
    root, data = found
    if change(data[section]):
        appconfig.write_config(root, data)
        _note(f"  noclick.json's {section} too, so the next deploy keeps it.")


def _put(section: Dict[str, Any], values: Dict[str, Any]) -> bool:
    """Set ``values`` in ``section``; whether that changed it."""
    changed = any(section.get(k) != v for k, v in values.items())
    section.update(values)
    return changed


def _drop(section: Dict[str, Any], names: Sequence[str]) -> bool:
    return [section.pop(n) for n in names if n in section] != []


def cmd_env_set(args: argparse.Namespace) -> int:
    project, link = _app(args)
    for name, value in args.pairs:
        project.settings.set(name, value)
        _note(f"Set {name} = {appconfig.clip(value)} on {project.name}.")
    _keep_in_step(link, "env", lambda env: _put(env, dict(args.pairs)))
    _note("They reach the app at its next deploy: noclick deploy.")
    _out(args, {"set": dict(args.pairs), "app": project.name}, None)
    return 0


def cmd_env_ls(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    found = project.settings.list()
    if getattr(args, "json", False):
        _out(args, {"data": found}, None)
        return 0
    output.table(("NAME", "VALUE"), sorted(found.items()), empty=f"{project.name} has no settings.")
    return 0


def cmd_env_rm(args: argparse.Namespace) -> int:
    project, link = _app(args)
    for name in args.names:
        project.settings.delete(name)
        _note(f"Deleted {name} from {project.name}; the app stops seeing it at its next deploy.")
    _keep_in_step(link, "env", lambda env: _drop(env, args.names))
    _out(args, {"deleted": args.names}, None)
    return 0


# --- bind ---------------------------------------------------------------------------------------------------------


def _binding_name(resource: str) -> str:
    """A binding's name from a resource's (``booking-db`` → ``BOOKING_DB``, ``ChatRoom`` → ``CHAT_ROOM``)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", resource)
    name = re.sub(r"[^A-Za-z0-9]+", "_", spaced).strip("_").upper()
    return name if name[:1].isalpha() else f"R_{name}"


def cmd_bind(args: argparse.Namespace) -> int:
    kind = _BIND_KINDS[args.kind]
    name = args.as_ or _binding_name(args.resource)
    if kind == "objects":
        return _bind_objects(args, name)
    project, link = _app(args)
    cls = _KINDS[kind]
    resource = cls.from_name(args.resource)
    made = False
    try:
        resource.id
    except NotFound:
        options: Dict[str, Any] = {}
        if kind == "database" and args.engine:
            options["engine"] = args.engine
        if kind == "bucket" and args.public:
            options["public"] = True
        if project.region:
            options["region"] = project.region
        resource = cls.from_name(args.resource, create_if_missing=True, **options)
        resource.id
        made = True
    else:
        if args.engine or args.public:
            _note(f"The {kind} {args.resource} exists already: --engine and --public only shape a new one.")
    binding = project.bind(name, resource)
    spec = {kind: args.resource, **({"engine": args.engine} if kind == "database" and args.engine else {}),
            **({"public": True} if kind == "bucket" and args.public else {})}
    _keep_in_step(link, "bindings", lambda bindings: _put(bindings, {name: spec}))
    _note(f"{'Made the' if made else 'Bound the'} {kind} {args.resource}{' and bound it' if made else ''} to "
          f"{project.name} as {name}. Its code reads it with Project.current().{kind}(\"{name}\") from the next "
          "deploy: noclick deploy.")
    _out(args, {"binding": binding.raw, "made": made}, name)
    return 0


def _bind_objects(args: argparse.Namespace, name: str) -> int:
    """A Durable Object class, which a Worker's wrangler config declares: its binding, and the migration that adds
    it."""
    folder = Path(args.dir or os.getcwd()).resolve()
    link = _link_of(folder)
    root = _root(link) if link else folder
    config = appconfig.read_config(root) if (root / appconfig.NOCLICK_JSON).is_file() else appconfig.AppConfig()
    app_folder = root / config.root if config.root else root
    path = appconfig.find_wrangler(app_folder)
    cls = args.resource
    binding = {"name": name, "class_name": cls}
    if path is None or path.suffix == ".toml":
        snippet = json.dumps({"durable_objects": {"bindings": [binding]},
                              "migrations": [{"tag": "v1", "new_sqlite_classes": [cls]}]}, indent=2)
        raise CommandError(
            f"A Durable Object runs in a Worker its wrangler config declares, and {app_folder} has "
            f"{'a TOML one, which noclick doesn’t edit' if path else 'none'}.",
            next_step=f"Declare it in {path.name if path else 'wrangler.jsonc (beside the worker’s main)'}: "
                      f"{snippet}", details={"snippet": snippet})
    text = path.read_text(encoding="utf-8-sig")
    data = appconfig.read_wrangler(path)
    objects = data.get("durable_objects") or {}
    bindings = list(objects.get("bindings") or [])
    if any(b.get("name") == name for b in bindings if isinstance(b, dict)):
        _note(f"{path.name} already binds {name}.")
        _out(args, {"binding": name, "changed": False}, name)
        return 0
    bindings.append(binding)
    migrations = list(data.get("migrations") or [])
    added = {c for m in migrations if isinstance(m, dict) for c in [*(m.get("new_sqlite_classes") or []),
                                                                       *(m.get("new_classes") or []),
                                                                       *(r.get("to") for r in m.get("renamed_classes")
                                                                         or [] if isinstance(r, dict))]}
    if cls not in added:
        migrations.append({"tag": f"v{len(migrations) + 1}", "new_sqlite_classes": [cls]})
    text = appconfig.set_top_level(text, "durable_objects", {**objects, "bindings": bindings})
    text = appconfig.set_top_level(text, "migrations", migrations)
    path.write_text(text)
    _note(f"{path.name} binds {name} to the Durable Object class {cls}"
          f"{', with a migration that adds it' if cls not in added else ''}. Export class {cls} from the worker's "
          f"main (it reaches the code as env.{name}), then noclick deploy.")
    _out(args, {"binding": name, "class_name": cls, "changed": True, "file": str(path)}, name)
    return 0


# --- domains ------------------------------------------------------------------------------------------------------


def cmd_domain_add(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    domain = project.add_domain(args.name)
    records = [r for r in domain.records if r.status != "verified"]
    if domain.status == "active":
        _note(f"{domain.name} serves {project.name} once its certificate is issued (a few minutes).")
    elif records:
        _note(f"{domain.name} is connected and waits for its DNS records ({domain.status}). Set these where its DNS "
              "is managed:")
        output.table(("TYPE", "NAME", "VALUE"), ((r.type, r.name, r.value) for r in records), empty="")
        _note(f"Then it goes live by itself; see where it stands with: noclick domains ls --app {project.name}")
    _out(args, {"domain": domain.raw}, f"https://{domain.name}")
    return 0 if domain.status in ("active", "pending_dns", "pending") else 1


def cmd_domain_ls(args: argparse.Namespace) -> int:
    project, _ = _app(args)
    found = project.domains()
    if getattr(args, "json", False):
        _out(args, {"data": [d.raw for d in found]}, None)
        return 0
    output.table(("DOMAIN", "STATUS", "SOURCE"), ((d.name, d.status, d.source) for d in found),
                empty=f"{project.name} answers only at {project.url}. Add one: noclick domains add <name>.")
    return 0


# --- the parser ---------------------------------------------------------------------------------------------------


def register(kit: Any) -> None:
    """Ship and configure: deploy, link, status, open, releases, rollback, promote, delete, secret, env, bind and
    the app's domains."""
    commands, command, group, as_json, user = kit.commands, kit.command, kit.group, kit.as_json, kit.user
    app = argparse.ArgumentParser(add_help=False)
    app.add_argument("--app", help="The app, by name or id (default: the one this folder is linked to).")
    wait = argparse.ArgumentParser(add_help=False)
    wait.add_argument("--no-wait", action="store_true", help="Print the operation id instead of waiting.")
    wait.add_argument("--timeout", type=float, metavar="SECONDS",
                      help="Stop waiting after this long (exit 124); it goes on, and noclick ops wait picks it up.")

    deploy = command(commands, "deploy", cmd_deploy, "Ship this folder to its app and print the live URL.",
                     parents=[as_json, user, wait])
    deploy.epilog = (
        "In a git checkout it ships the commit you're on; with uncommitted or untracked files, a snapshot of the "
        "folder as a commit of its own on top (your checkout never changes), naming each file. Outside git it "
        "commits the folder through the API. Files that look like secrets (.env, keys) are left out, each named "
        "with the noclick secret set command for its values; one committed in the commit it ships refuses it. The "
        "folder's first deploy makes its app (named after it) and links it. noclick.json's bindings, env and crons "
        "are given to the app first, and a wrangler config's vars, D1, KV, R2 and crons are written into noclick.json. Once "
        "live, its home page and the app's check paths are loaded: when they fail it prints the warning and what to "
        "fix, and exits 1 (the deployment stays live).")
    deploy.add_argument("app_ref", nargs="?", metavar="APP", help="The app (default: this folder's).")
    deploy.add_argument("--app", help="The app, as a flag: the same as the argument.")
    deploy.add_argument("--dir", help="The app's folder (default: this one).")
    where = deploy.add_mutually_exclusive_group()
    where.add_argument("--branch", help="Ship as this branch: the production branch goes live, any other is a preview.")
    where.add_argument("--prod", action="store_true", help="Ship to the app's production branch.")
    where.add_argument("--preview", nargs="?", const="", metavar="NAME",
                       help="Ship as a preview (named NAME, else after your branch, else 'preview').")
    deploy.add_argument("--only-committed", action="store_true",
                        help="Ship the commit you're on alone; refuse uncommitted or untracked files.")
    deploy.add_argument("--no-git", action="store_true", help="Ship the folder through the API even in a checkout.")
    deploy.add_argument("--create", action="store_true", help="With an app named that doesn't exist: make it.")
    deploy.add_argument("--budget", type=float, metavar="USD",
                        help="The app's monthly budget in dollars: what it may spend on hosting, its data, email, AI "
                             "and agents (set, or changed, with this deploy).")
    deploy.add_argument("--token", help="A deploy token, as NoClick's MCP server hands an agent with the command "
                                        "(it reaches one repo and its apps), instead of your key.")

    link = command(commands, "link", cmd_link, "Tie this folder to an app, so commands here act on it.",
                   parents=[as_json])
    link.add_argument("app_ref", nargs="?", metavar="APP", help="The app, by name or id.")
    link.add_argument("--app", help=argparse.SUPPRESS)
    link.add_argument("--dir", help="The folder (default: this one).")
    link.add_argument("--create", action="store_true",
                      help="Make the app (and its repo) when there's none by that name.")
    link.add_argument("--budget", type=float, metavar="USD", help="With --create: its monthly budget in dollars.")
    unlink = command(commands, "unlink", cmd_unlink, "Untie this folder from its app (the app is unchanged).",
                     parents=[as_json])
    unlink.add_argument("--dir", help="The folder (default: this one).")

    command(commands, "status", cmd_status,
            "Everything about the app on one screen: URLs, the live release and its health, errors, bindings, "
            "secrets, settings and spend.", parents=[as_json, user, app])
    opened = command(commands, "open", cmd_open, "Print the app's URL, and open it at a terminal.",
                     parents=[as_json, user, app])
    opened.add_argument("--preview", nargs="?", const="", metavar="BRANCH", help="A preview's URL instead.")
    opened.add_argument("--no-browser", action="store_true", help="Print it only.")
    releases = command(commands, "releases", cmd_releases, "List the app's releases, newest first.",
                       parents=[as_json, user, app])
    releases.add_argument("--all", action="store_true", help="Previews too.")
    releases.add_argument("--limit", type=int, default=10, help="At most this many (default 10).")
    rollback = command(commands, "rollback", cmd_rollback,
                       "Serve an earlier release again, without rebuilding (default: the one before the live one).",
                       parents=[as_json, user, app, wait])
    rollback.add_argument("release", nargs="?", help="Its id, or its commit (7+ characters).")
    promote = command(commands, "promote", cmd_promote, "Put a preview live in production, after its checks.",
                      parents=[as_json, user, app, wait])
    promote.add_argument("preview", help="The preview: its branch, URL or deployment id.")
    promote.add_argument("--force", action="store_true", help="Promote it without the app's checks.")
    delete = command(commands, "delete", cmd_delete,
                     "Delete the app to the trash: says what goes first, and deletes only with --yes.",
                     parents=[as_json, user, app])
    delete.add_argument("--yes", action="store_true", help="Delete it (without it, nothing is deleted).")
    delete.add_argument("--delete-data", action="store_true",
                        help="Its repo, and each database and bucket no other app binds, go to the trash too.")

    secret = group("secret", "Set the app's secrets: values never echo, never in argv.")
    environment = argparse.ArgumentParser(add_help=False)
    environment.add_argument("--env", choices=("all", "production", "preview"), default="all",
                             help="Which deploys see it (default: all).")
    put = command(secret, "set", cmd_secret_set, "Set a secret from a variable of this shell, or stdin.",
                  parents=[as_json, user, app, environment])
    put.add_argument("name")
    source = put.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-env", metavar="VAR", help="This shell's variable holding the value.")
    source.add_argument("--stdin", action="store_true", help="Read the value from stdin (a trailing newline dropped).")
    command(secret, "ls", cmd_secret_ls, "List the secrets' names (never their values).",
            parents=[as_json, user, app, environment])
    rm = command(secret, "rm", cmd_secret_rm, "Delete secrets.", parents=[as_json, user, app, environment])
    rm.add_argument("names", nargs="+", metavar="NAME")

    env = group("env", "Set the app's plain settings (they read back; keep secrets in noclick secret).")
    put = command(env, "set", cmd_env_set, "Set settings, each KEY=value.", parents=[as_json, user, app])
    put.add_argument("pairs", nargs="+", type=_pair, metavar="KEY=value")
    command(env, "ls", cmd_env_ls, "List the settings and their values.", parents=[as_json, user, app])
    rm = command(env, "rm", cmd_env_rm, "Delete settings.", parents=[as_json, user, app])
    rm.add_argument("names", nargs="+", metavar="KEY")

    bind = command(commands, "bind", cmd_bind,
                   "Give the app a database, bucket, dict, queue or Durable Object class, made if it's missing.",
                   parents=[as_json, user, app])
    bind.add_argument("kind", choices=sorted(_BIND_KINDS), help="db, bucket, dict, queue, or objects (a Durable "
                                                                "Object class, declared in the wrangler config).")
    bind.add_argument("resource", metavar="NAME", help="The resource's name (for objects, the class's).")
    bind.add_argument("--as", dest="as_", metavar="BINDING",
                      help="The name the code reads it by (default: NAME in capitals, booking-db → BOOKING_DB).")
    bind.add_argument("--engine", choices=("sqlite", "postgres"), help="A new database's engine (default sqlite).")
    bind.add_argument("--public", action="store_true", help="A new bucket's files are public.")
    bind.add_argument("--dir", help="For objects: the app's folder (default: this one).")

    # The app's domains join the domains group (search, buy).
    domains = kit.groups.get("domains") or group("domains", "Search for and buy domains, and serve the app at them.")
    add = command(domains, "add", cmd_domain_add, "Serve the app at a domain, and print the DNS records to set.",
                  parents=[as_json, user, app])
    add.add_argument("name", help="The domain, like book.acme.com.")
    command(domains, "ls", cmd_domain_ls, "List the domains serving the app.", parents=[as_json, user, app])
