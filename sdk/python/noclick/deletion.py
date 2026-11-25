"""What a deletion would do, before it's made: ``preview_delete`` names a ``DELETE`` (or a closing ``POST``) and says
what goes with it, what stops working, what data is lost, what stops billing and whether it can be taken back, with
the confirm token the call itself needs where the account's policy asks for one."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._client import Client, resolve_client
from ._scope import AMBIENT, resolve_scope
from ._sync import synced


@dataclass(frozen=True)
class DeletionImpact:
    """What a deletion does, in words a person reads before agreeing: what it ``deletes``, what has to go first or
    stops working with it (``depends_on_it``), the data it loses, what stops billing, and whether it can be taken back
    (``reversible``; ``undo`` says how)."""

    deletes: str
    depends_on_it: List[str]
    data_lost: List[str]
    stops_billing: List[str]
    reversible: bool
    undo: Optional[str]


@dataclass(frozen=True)
class DeletionPreview:
    """A deletion previewed: its ``operation``, ``method`` and ``path``, what it's called (``title``), its ``impact``,
    and the ``confirm_token`` (good for ``expires_in_s`` seconds) the call takes."""

    operation: str
    method: str
    path: str
    title: Optional[str]
    impact: DeletionImpact
    confirm_token: str
    expires_in_s: int
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


@synced
async def preview_delete(method: str, path: str, *, body: Any = None, user: Any = AMBIENT,
                         client: Optional[Client] = None) -> DeletionPreview:
    """What ``method path`` would delete (``DELETE``, or ``POST`` for a cancel, close or clear), as the account sees it
    (``user``: as one of its users does): what goes, what depends on it, what data is lost and whether it can be taken
    back. ``body`` is the call's own, for a deletion judged by it (a workflow's edits that remove steps). Nothing is
    deleted.

    Returns:
        The preview.

    Usage::

        preview = noclick.preview_delete("DELETE", f"/v1/agents/{agent.id}")
        print(preview.impact.deletes, preview.impact.undo if preview.impact.reversible else "for good")
    """
    sent: Dict[str, Any] = {"method": method, "path": path}
    if body is not None:
        sent["body"] = body
    raw = await resolve_client(client).request("POST", "/v1/delete_previews", json=sent, user=resolve_scope(user)) or {}
    impact = raw.get("impact") or {}
    return DeletionPreview(
        raw.get("operation") or "", raw.get("method") or method, raw.get("path") or path, raw.get("title"),
        DeletionImpact(impact.get("deletes") or "", list(impact.get("depends_on_it") or []),
                       list(impact.get("data_lost") or []), list(impact.get("stops_billing") or []),
                       impact.get("reversible") is True, impact.get("undo")),
        raw.get("confirm_token") or "", int(raw.get("expires_in_s") or 0), raw)
