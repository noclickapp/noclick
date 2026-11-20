"""A workflow's Approval steps: the runs that wait at one for a yes or a no, read and answered from your own code.

A run that reaches an Approval step waits there, for 7 days at most. NoClick asks your account's owner to answer it:
a one-tap link on the app they text NoClick on (else by email), or a card in the web chat while they're watching it.
Your code may answer it too, with one of your account's secret keys that names the ``approvals:answer`` scope (a key
with every scope, ``*``, holds it only when it's named too)::

    invoices = noclick.Workflow.from_name("Invoices")
    for approval in invoices.approvals(status="pending"):
        if float(approval.values.get("amount") or 0) < 500:
            approval.approve(note="Under $500: fine.")

Whoever answers first decides: the run goes on once, down the step's approved or rejected branch, with the form's
values as they were answered, and every later answer is refused (``noclick.Conflict``), as one after the 7 days is
(``noclick.Expired``).

Rather than poll, your code can hear each one: a webhook subscribed to ``workflow.approval.requested`` gets it as its
run starts waiting, and to ``workflow.approval.decided`` as it's answered. The event's ``data`` is the approval as it
reads here, never its link::

    event = noclick.Webhook.verify(body, headers, secret)
    if event.type == "workflow.approval.requested":
        noclick.WorkflowApproval.from_id(event.data["workflow_id"], event.data["id"]).decline(
            note="Nothing is paid on weekends.")
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import _Object, compact, field, list_all, parse_time
from ._sync import synced

STATUSES = ("pending", "approved", "declined", "expired")


def _workflow_id(workflow: Any) -> str:
    """A workflow's id, from a ``noclick.Workflow`` (by id or name) or the id itself."""
    return workflow if isinstance(workflow, str) else workflow.id


class WorkflowApproval(_Object):
    """An Approval step a run of one of your workflows waits at (or waited at), as its owner sees it."""

    _repr_keys = ("id", "status", "title")

    id: str = field("id")
    workflow_id: str = field("workflow_id")
    workflow_name: Optional[str] = field("workflow_name")
    run_id: str = field("run_id", doc="The run that waits at it (``workflow.get_run(run_id)``).")
    step: str = field("step", doc="The Approval step's id in the workflow.")
    title: Optional[str] = field("title", doc="What it asks, as the step's title says it.")
    fields: List[Dict[str, Any]] = field(
        "fields", doc="Its form's fields, each with ``name``, ``type``, ``label``, ``description``, ``required`` "
        "and ``options``.",
    )
    values: Dict[str, Any] = field(
        "values", doc="The form's values by field name: as the run asked, then as it was answered.",
    )
    status: str = field("status", doc=f"One of {', '.join(STATUSES)}.")
    created_at: Any = field("created_at", parse_time)
    expires_at: Any = field("expires_at", parse_time, doc="When it lapses unanswered (7 days after it was asked).")
    decided_at: Any = field("decided_at", parse_time)
    decided_by: Optional[str] = field(
        "decided_by", doc="Who decided: ``owner`` (signed in, or from NoClick's link or the web chat), ``code`` or "
        "``app`` (someone who may edit the workflow, in the NoClick app); None while it waits.",
    )
    decided_by_key: Optional[Dict[str, Any]] = field(
        "decided_by_key", doc="The key whose code decided (``key_id``, ``key_name``); None otherwise.",
    )
    note: Optional[str] = field("note", doc="What whoever decided wrote with it.")
    sent_to: List[str] = field(
        "sent_to", doc="Where NoClick sent the owner its link: ``whatsapp``, ``imessage``, ``email``, or ``web`` (a "
        "card in the chat they were watching).",
    )

    @classmethod
    def from_id(cls, workflow: Any, approval_id: str, *, client: Optional[Client] = None) -> "WorkflowApproval":
        """A lazy reference to one of a workflow's Approval steps by its id (an event's ``data["id"]``).

        Returns:
            The approval; it loads the first time it's used.

        Usage::

            approval = noclick.WorkflowApproval.from_id(event.data["workflow_id"], event.data["id"])
            print(approval.title, approval.values)
        """
        return cls._new(hints={"id": approval_id, "workflow_id": _workflow_id(workflow)}, client=client, user=None)

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path(), user=None)

    def _path(self, suffix: str = "") -> str:
        workflow_id = quote(str(self._known("workflow_id")), safe="")
        return f"/v1/workflows/{workflow_id}/approvals/{quote(str(self._known('id')), safe='')}{suffix}"

    @synced
    @classmethod
    async def list(
        cls, workflow: Any, *, status: Optional[str] = None, limit: Optional[int] = None,
        client: Optional[Client] = None,
    ) -> List["WorkflowApproval"]:
        """A workflow's Approval steps, newest first: the first 20, or the first ``limit`` (at most 100), with
        ``status`` one of ``pending``, ``approved``, ``declined`` or ``expired``. Read as your account, with a key
        holding ``workflows`` or ``approvals:answer``.

        Returns:
            Each approval as its owner sees it.

        Usage::

            for approval in noclick.WorkflowApproval.list("2e3a9296-...", status="pending"):
                print(approval.title, approval.values, approval.expires_at)
        """
        return await list_all(
            f"/v1/workflows/{quote(_workflow_id(workflow), safe='')}/approvals",
            lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params={"status": status}, user=None, limit=limit, client=client,
        )

    async def _answer(self, approved: bool, note: Optional[str],
                      values: Optional[Dict[str, Any]]) -> "WorkflowApproval":
        self._raw = await resolve_client(self._client).request(
            "POST", self._path("/answer"), json=compact(approved=approved, note=note, values=values), user=None)
        return self

    @synced
    async def approve(self, *, note: Optional[str] = None,
                      values: Optional[Dict[str, Any]] = None) -> "WorkflowApproval":
        """Approve it from your own code, with one of your account's secret keys that names the ``approvals:answer``
        scope: the run goes on down the step's approved branch, once, with ``values`` (by field name) as the form's
        values where you give them. Refused with ``noclick.PermissionDenied`` for a key without the scope or one
        acting for a user, ``noclick.Conflict`` once it was answered, and ``noclick.Expired`` after its 7 days.

        Returns:
            This approval, answered: ``status`` is ``approved``, ``decided_by`` is ``code``.

        Usage::

            approval = noclick.WorkflowApproval.from_id(workflow_id, approval_id)
            approval.approve(note="Checked the invoice.", values={"amount": "420"})
        """
        return await self._answer(True, note, values)

    @synced
    async def decline(self, *, note: Optional[str] = None,
                      values: Optional[Dict[str, Any]] = None) -> "WorkflowApproval":
        """Decline it from your own code, as ``approve`` answers it: the run goes on down the step's rejected branch.

        Returns:
            This approval, answered: ``status`` is ``declined``.

        Usage::

            for approval in noclick.Workflow.from_name("Invoices").approvals(status="pending"):
                approval.decline(note="Invoices wait for Monday's review.")
        """
        return await self._answer(False, note, values)
