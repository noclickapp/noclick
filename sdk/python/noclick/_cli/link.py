"""The folder's linked app: ``.noclick/project.json`` at the folder's root (the git checkout's, else the folder
where it was written), naming the app by name and id and the API it's on, so a command run anywhere in the folder
needs no app named. Never a key: the key stays where ``noclick login`` or ``noclick setup`` kept it."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..exceptions import Error
from . import exits

FOLDER = ".noclick"
FILE = "project.json"


class NotLinked(exits.Suggests, Error):
    """A command that needs an app ran where none is named or linked."""

    type = "not_linked"


@dataclass(frozen=True)
class Link:
    """The app a folder is linked to, and where the link is kept."""

    app: str
    app_id: Optional[str]
    api_url: Optional[str]
    path: Path


def find(start: Optional[Path] = None) -> Optional[Link]:
    """The link of ``start`` (default: here) or the nearest folder above it holding one."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        path = folder / FOLDER / FILE
        if path.is_file():
            data = json.loads(path.read_text())
            return Link(str(data["app"]), data.get("app_id"), data.get("api_url"), path)
    return None


def write(app: str, *, app_id: Optional[str] = None, api_url: Optional[str] = None,
          root: Optional[Path] = None) -> Link:
    """Link ``root`` (default: here) to ``app``. A ``.noclick/.gitignore`` keeps the folder out of commits, since
    the link is this machine's."""
    folder = (root or Path.cwd()) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".gitignore").write_text("*\n")
    path = folder / FILE
    path.write_text(json.dumps({"app": app, "app_id": app_id, "api_url": api_url}, indent=2) + "\n")
    return Link(app, app_id, api_url, path)


def remove(start: Optional[Path] = None) -> Optional[Link]:
    """Forget the link ``find`` reads; the link it was, or None for none."""
    found = find(start)
    if found is not None:
        found.path.unlink()
        if not any(p.name != ".gitignore" for p in found.path.parent.iterdir()):
            for p in found.path.parent.iterdir():
                p.unlink()
            os.rmdir(found.path.parent)
    return found


def app_name(named: Optional[str], *, start: Optional[Path] = None) -> str:
    """The app a command acts on: the one it names, else the folder's linked one."""
    if named:
        return named
    found = find(start)
    if found is not None:
        return found.app
    raise NotLinked("Name the app: this folder isn't linked to one.",
                    next_step="Pass the app's name, or link this folder once: noclick link <app>",
                    run=["noclick link <app>"])
