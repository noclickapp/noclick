"""What a harness format is: how to find this conversation's thread in the
harness's store, how to read it into a ``Thread``, and how to write a
``Thread`` as the store the harness will resume.

One subclass per harness, registered in ``formats/__init__.py``. The base
carries what every file-backed store shares — JSONL reading with a size
cap, the create-if-absent write a mounted volume accepts, the newest-file
rule — so a format module is only the harness's record vocabulary.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..ir import Event, StoreRef, TargetIdentity, Thread

#: A store larger than this is not a conversation we move at cold start.
MAX_STORE_BYTES = 512 * 1024 * 1024


class InterchangeError(Exception):
    """A move that must not proceed. ``reason`` is one of ``REASONS``; the
    verdict stamps it and the report keys on it."""

    def __init__(self, reason: str, detail: str = ""):
        if reason not in REASONS:
            raise ValueError(f"unknown interchange reason {reason!r}")
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


#: The complete vocabulary a verdict can carry, with what each means for
#: the caller. Keep this the one list: reports, tests and dashboards key on it.
REASONS: Dict[str, str] = {
    "no_adapter": "no format module for one of the harnesses",
    "same_harness": "source and target are the same harness — nothing to move",
    "sdk_source": "the in-process agent keeps its history in the conversation row, not a harness store",
    "source_empty": "the source store holds no thread for this conversation (the target's own store is current)",
    "source_unreadable": "the source thread could not be parsed — a harness format drifted",
    "source_too_large": "the source store exceeds MAX_STORE_BYTES",
    "empty_source": "the source thread holds no messages",
    "fidelity_drop": "the translation would lose something structural (see detail)",
    "install_failed": "the target store could not be written",
    "readback_failed": "the written store could not be read back through the target's reader",
    "readback_mismatch": "the written store reads back with a different skeleton than the source",
    "translator_crashed": "the move raised outside its own vocabulary — a bug",
}


@dataclass
class Written:
    """A writer's output: the native records in order, where they belong,
    and what the writer could not represent. ``install`` may leave what it
    needs to take the write back again in ``undo``."""

    session_id: str
    native_path: Path
    records: List[Dict[str, Any]]
    dropped: Counter = field(default_factory=Counter)
    warnings: List[str] = field(default_factory=list)
    undo: Dict[str, Any] = field(default_factory=dict)


class ThreadFormat:
    """A harness's session store, as far as moving threads is concerned.

    Subclasses set ``harness`` and implement ``locate``, ``read`` and
    ``write``. ``describe`` is free: it is what ``inspect`` and the docs
    print, so keep the class docstring an honest description of the store."""

    harness: str = ""

    # ── the contract ────────────────────────────────────────────────────────

    def locate(self, store: StoreRef) -> str:
        """The thread this store holds for the conversation: a path for
        file-backed stores. Prefers the runner's pointer (the exact thread it
        would resume). Raises ``source_empty`` when there is nothing."""
        raise NotImplementedError

    def read(self, ref: str) -> Thread:
        """The thread at ``ref`` as a ``Thread``. Raises ``source_unreadable``
        on a shape the reader does not understand."""
        raise NotImplementedError

    def write(self, thread: Thread, store: StoreRef, identity: TargetIdentity) -> Written:
        """``thread`` as this harness's native records, addressed under
        ``store``. Does not touch the store — ``install`` does."""
        raise NotImplementedError

    def install(self, written: Written, store: Optional[StoreRef] = None) -> Path:
        """Land the records where the harness reads them. File-backed stores
        get a plain create-if-absent write (``O_EXCL``, mode 0600 where the
        filesystem honours it) with no rename, link or chmod after it — the
        FUSE-backed session volumes the hosted sandboxes mount reject those
        with EPERM. Database-backed formats override this."""
        data = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in written.records).encode()
        write_new_file(written.native_path, data)
        return written.native_path

    def ref_for(self, written: Written, store: StoreRef) -> str:
        """The ``read`` reference for what ``install`` landed — the verdict
        reads the store back through it."""
        return str(written.native_path)

    def unwrite(self, written: Written, store: StoreRef) -> None:
        """Take a failed install back so the harness never resumes it."""
        discard(written.native_path)

    def describe(self) -> Dict[str, Any]:
        first_paragraph = (self.__doc__ or "").strip().split("\n\n", 1)[0]
        return {"harness": self.harness, "store": " ".join(first_paragraph.split())}

    # ── shared mechanics ────────────────────────────────────────────────────

    @staticmethod
    def read_jsonl(path: Path) -> Tuple[List[Tuple[int, Any]], int, str]:
        """``[(index, value)]`` for every parseable line, the total line
        count, and the file's sha256. A line that is not JSON is skipped and
        surfaces through the count difference."""
        size = path.stat().st_size
        if size > MAX_STORE_BYTES:
            raise InterchangeError("source_too_large", f"{path} is {size} bytes")
        raw = path.read_bytes()
        records: List[Tuple[int, Any]] = []
        total = 0
        for index, line in enumerate(raw.decode("utf-8", errors="replace").splitlines()):
            if not line.strip():
                continue
            total += 1
            try:
                records.append((index, json.loads(line)))
            except ValueError:
                continue
        return records, total, hashlib.sha256(raw).hexdigest()

    @staticmethod
    def newest(paths: Iterable[Path]) -> Optional[Path]:
        files = [p for p in paths if p.is_file()]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    @staticmethod
    def new_session_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    @staticmethod
    def sha(thread: Thread) -> str:
        return thread.sha256 or ""


def db_ref(db: Path, session_id: str) -> str:
    """A ``read`` reference into a database-backed store."""
    return f"{db}#{session_id}"


def split_db_ref(ref: str) -> Tuple[Path, str]:
    db, sep, session_id = ref.rpartition("#")
    if not sep or not db:
        raise InterchangeError("source_unreadable", f"not a database reference: {ref!r}")
    return Path(db), session_id


def pointer_text(pointer: Optional[Path]) -> Optional[str]:
    """What a runner's pointer file names, or None."""
    if pointer is None:
        return None
    try:
        return pointer.read_text().strip() or None
    except OSError:
        return None


def write_new_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass  # a volume that does not fsync still persists on commit
    except BaseException:
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def discard(*paths: Optional[Path]) -> None:
    for p in paths:
        if p is None:
            continue
        try:
            if p.is_file():
                os.remove(p)
        except OSError:
            pass
