"""Moving a thread: read the source store, write the target store, and
prove the target holds the same conversation before anyone resumes it.

The verdict is not "the writer ran": the written store is read BACK through
the target harness's own reader, and its skeleton (every message with its
text, every tool call paired with its result, in order) must equal the
source's. Drops on either side are classified — bookkeeping and
provider-bound reasoning are the accepted cost of leaving a harness,
anything structural fails — and a failed verdict removes what it wrote.
Every move leaves a manifest beside the target store with the source's
fingerprint, the identity written, the drops and the verdict, so a thread
can always be traced to what produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .formats import InterchangeError, Written, discard, format_for, write_new_file
from .ir import INTERCHANGE_VERSION, Skeleton, StoreRef, TargetIdentity, Thread, classify_drops, skeleton_of

MANIFEST_DIR = ".nc_interchange"


@dataclass
class Fidelity:
    source: Skeleton
    target: Skeleton
    dropped: Dict[str, int] = field(default_factory=dict)
    rejected_drops: Dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (
            not self.rejected_drops
            and self.source.roles == self.target.roles
            and self.source.digest == self.target.digest
            and self.source.tool_calls == self.target.tool_calls
            and self.source.tool_results == self.target.tool_results
            and self.target.unpaired_tool_calls == 0
        )

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "source": self.source.as_dict(), "target": self.target.as_dict(),
                "dropped": self.dropped, "rejected_drops": self.rejected_drops}


@dataclass
class InterchangeResult:
    source_harness: str
    target_harness: str
    session_id: str
    native_path: Path
    manifest_path: Path
    fidelity: Fidelity
    version: str = INTERCHANGE_VERSION

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": True, "source_harness": self.source_harness, "target_harness": self.target_harness,
            "session_id": self.session_id, "native_path": str(self.native_path), "manifest_path": str(self.manifest_path),
            "fidelity": self.fidelity.as_dict(), "interchange_version": self.version,
        }


def read_thread(store: StoreRef) -> Thread:
    """This conversation's thread from ``store``, located the way the
    harness itself would resume it."""
    fmt = format_for(store.harness)
    ref = fmt.locate(store)
    try:
        return fmt.read(ref)
    except InterchangeError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise InterchangeError("source_unreadable", f"{ref}: {type(e).__name__}: {e}") from e


def translate(thread: Thread, target: StoreRef, identity: Optional[TargetIdentity] = None) -> InterchangeResult:
    """Write ``thread`` into ``target``'s store and return the verdict. Raises
    ``InterchangeError`` when the target would not hold the conversation
    faithfully; the store is left in place only when the verdict passed."""
    identity = identity or TargetIdentity()
    fmt = format_for(target.harness)
    source_skeleton = skeleton_of(thread)
    if source_skeleton.messages == 0:
        raise InterchangeError("empty_source", "the source thread holds no messages")
    written = fmt.write(thread, target, identity)
    dropped = dict(thread.dropped) | dict(written.dropped)
    rejected = classify_drops(dropped)
    if rejected:
        raise InterchangeError("fidelity_drop", json.dumps(rejected, sort_keys=True))
    try:
        fmt.install(written)
    except OSError as e:
        raise InterchangeError("install_failed", f"{written.native_path}: {e.strerror or e}") from e
    try:
        back = fmt.read(str(written.native_path))
    except (InterchangeError, OSError, ValueError, KeyError, TypeError) as e:
        discard(written.native_path)
        raise InterchangeError("readback_failed", str(e)) from e
    fidelity = Fidelity(source=source_skeleton, target=skeleton_of(back), dropped=dropped, rejected_drops=rejected)
    if not fidelity.ok:
        discard(written.native_path)
        raise InterchangeError("readback_mismatch", json.dumps(fidelity.as_dict(), sort_keys=True))
    manifest_path = _write_manifest(thread, target, identity, written, fidelity)
    return InterchangeResult(
        source_harness=thread.harness, target_harness=target.harness, session_id=written.session_id,
        native_path=written.native_path, manifest_path=manifest_path, fidelity=fidelity,
    )


def move_thread(source: StoreRef, target: StoreRef, identity: Optional[TargetIdentity] = None) -> InterchangeResult:
    """Move this conversation's thread from ``source`` into ``target``'s
    store and point ``target``'s runner at it. ``source_empty`` means there
    was nothing to move (the target's own store is current) — not a failure."""
    if source.harness == target.harness:
        raise InterchangeError("same_harness")
    format_for(target.harness)  # judged before the source is touched
    result = translate(read_thread(source), target, identity)
    if target.pointer is not None:
        target.pointer.parent.mkdir(parents=True, exist_ok=True)
        target.pointer.write_text(result.session_id)
    return result


def inspect_store(store: StoreRef) -> Dict[str, Any]:
    """What ``store`` holds for this conversation — for debugging a move
    from either end without moving anything."""
    thread = read_thread(store)
    turns = [{"provenance": str(e.provenance), "role": e.role, "text": (e.text or "")[:120]} for e in thread.events if e.is_turn]
    return {"store": store.as_dict(), "thread": thread.summary(), "skeleton": skeleton_of(thread).as_dict(),
            "rejected_drops": classify_drops(dict(thread.dropped)), "turns": turns[:50], "turns_total": len(turns)}


def _write_manifest(thread: Thread, target: StoreRef, identity: TargetIdentity, written: Written, fidelity: Fidelity) -> Path:
    path = target.home / MANIFEST_DIR / f"{written.session_id}.json"
    manifest = {
        "interchange_version": INTERCHANGE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {"harness": thread.harness, "ref": thread.source, "session_id": thread.session_id,
                   "sha256": thread.sha256, "records": thread.records, "cli_version": thread.cli_version},
        "target": {"harness": target.harness, "path": str(written.native_path), "session_id": written.session_id,
                   "records": len(written.records), "identity": identity.as_dict()},
        "fidelity": fidelity.as_dict(),
        "warnings": written.warnings,
    }
    try:
        write_new_file(path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    except OSError:
        pass  # the manifest is a debugging aid; the store is what matters
    return path


def parse_verdict(stdout: str) -> Dict[str, Any]:
    """The verdict the CLI printed — the LAST JSON line of stdout."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                verdict = json.loads(line)
            except ValueError:
                continue
            if isinstance(verdict, dict) and "ok" in verdict:
                return verdict
    return {"ok": False, "reason": "translator_crashed", "detail": f"no verdict in output: {stdout[-500:]!r}"}


__all__ = ["Fidelity", "InterchangeResult", "MANIFEST_DIR", "inspect_store", "move_thread", "parse_verdict", "read_thread", "translate"]
