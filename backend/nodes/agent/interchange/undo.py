"""Putting files back as they were before a conversation's dropped turns edited them (a revert, run in the agent's
sandbox before its harness starts): each kept edit's diff applied in reverse, newest first. A file goes back only
when every edit of it reverses cleanly, else it is left as it is and says why (it changed since, or its edit kept no
content to go back to). Stdlib only, shipped with the interchange."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
CHANGED_SINCE = "It changed after that edit, so it was left as it is."
NOTHING_KEPT = "Its edit kept no content to go back to."


def _hunks(diff: str) -> List[Tuple[int, List[str], List[str]]]:
    """``(the new side's first line, its lines, the old side's lines)`` per hunk of a unified diff."""
    out: List[Tuple[int, List[str], List[str]]] = []
    current: Optional[Tuple[int, List[str], List[str]]] = None
    for line in diff.split("\n"):
        head = _HUNK.match(line)
        if head:
            current = (int(head.group(3)), [], [])
            out.append(current)
        elif current is not None and line[:1] in (" ", "+", "-"):
            if line[0] in (" ", "+"):
                current[1].append(line[1:])
            if line[0] in (" ", "-"):
                current[2].append(line[1:])
        elif current is not None and line == "":
            continue  # the split's last piece, or a blank context line a harness wrote without its space
    return out


def _find(lines: List[str], block: List[str], near: int) -> Optional[int]:
    """Where ``block`` starts in ``lines``, the match nearest ``near`` (0-based)."""
    if not block:
        return min(max(near, 0), len(lines))
    starts = [i for i in range(len(lines) - len(block) + 1) if lines[i:i + len(block)] == block]
    return min(starts, key=lambda i: abs(i - near)) if starts else None


def _reverse(text: str, diff: str) -> Optional[str]:
    """``text`` with the edit ``diff`` made to it taken back; None when the file no longer holds what it made."""
    trailing = text.endswith("\n")
    lines = text.split("\n")[:-1] if trailing else text.split("\n")
    for start, new, old in reversed(_hunks(diff)):
        at = _find(lines, new, start - 1)
        if at is None:
            return None
        lines[at:at + len(new)] = old
    return "\n".join(lines) + ("\n" if trailing else "")


def _added(diff: str) -> str:
    """What an edit that made a file wrote: its diff's added lines, or the whole content a harness reports."""
    hunks = _hunks(diff)
    return "\n".join(new for _, lines, _ in hunks for new in lines) if hunks else diff


def _same(a: str, b: str) -> bool:
    return a.rstrip("\n") == b.rstrip("\n")


def _undo_one(path: Path, edit: Dict[str, Any]) -> Optional[str]:
    """Take one edit of ``path`` back; why not, or None when it went back."""
    change, diff = edit.get("change") or "update", edit.get("diff") or ""
    if change == "add":
        if not path.exists():
            return None  # gone already
        if not _same(path.read_text(), _added(diff)):
            return CHANGED_SINCE
        path.unlink()
        return None
    if change == "delete":
        old = "\n".join(line for _, _, side in _hunks(diff) for line in side)
        if not _hunks(diff):
            return NOTHING_KEPT
        if path.exists():
            return CHANGED_SINCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(old + "\n")
        return None
    if not _hunks(diff):
        return NOTHING_KEPT
    if not path.exists():
        return CHANGED_SINCE
    back = _reverse(path.read_text(), diff)
    if back is None:
        return CHANGED_SINCE
    path.write_text(back)
    return None


def undo_edits(edits: List[Dict[str, Any]], cwd: Path) -> List[Dict[str, Any]]:
    """``edits`` newest first (``{path, change, diff}``), a path relative to ``cwd``: each file's verdict,
    ``{path, restored}`` with ``why`` when it wasn't. A file's edits all go back or none do (its content is kept
    until they all have)."""
    by_path: Dict[str, List[Dict[str, Any]]] = {}
    for edit in edits:
        by_path.setdefault(edit.get("path") or "", []).append(edit)
    verdicts = []
    for name, its in by_path.items():
        if not name:
            continue
        path = Path(name) if os.path.isabs(name) else cwd / name
        before = path.read_bytes() if path.is_file() else None
        why = None
        try:
            for edit in its:
                why = _undo_one(path, edit)
                if why:
                    break
        except (OSError, UnicodeDecodeError) as exc:
            why = f"It couldn't be read or written: {exc.strerror or exc}"
        if why:
            # Every edit of it or none: what went back already is put as it was.
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
        verdicts.append({"path": name, "restored": why is None, **({"why": why} if why else {})})
    return verdicts
