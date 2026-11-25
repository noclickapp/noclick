"""What your workflows keep: the files their steps and interfaces stored, and the tables they keep rows in.

    intake = noclick.Workflow.from_name("Order intake")
    for file in noclick.WorkflowFile.list(workflow=intake):
        print(file.name, file.size_bytes, file.url)
    [orders] = noclick.WorkflowTable.list(workflow=intake)
    print(orders.row_count, [row.data for row in orders.rows(limit=5)])

A list holds what each workflow ``Workflow.get`` reads keeps: your account's
own, those shared with it, and the ones its agents run on. They're the
account's, not any one user's: a call acting for one of your users (inside
``as_user``, or with a key held to one) is refused with
``noclick.PermissionDenied``. An app's own code reads only what the workflows its
code made keep, one workflow at a time (``workflow=``). ``organization_id`` narrows a list to the workflows in a
team workspace of the NoClick app your account belongs to (``"none"``: those
in no workspace).

A file's ``url`` reads it for an hour after it's listed; a picture, PDF, sound
or video opens in place, anything else downloads. A table's rows read in pages
of up to 10,000. Deleting either takes edit access to its workflow and is
for good: nothing keeps a copy, and there's no trash to restore it from.

Making a file or a table, and adding, changing or taking out a table's rows,
take edit access to its workflow, as an interface's own uploads and writes do::

    menu = noclick.WorkflowFile.create(intake, "menu.pdf", size_bytes=len(data), mime_type="application/pdf")
    httpx.put(menu.upload_url, content=data, headers={"Content-Type": "application/pdf"})
    signups = noclick.WorkflowTable.create(intake, "Signups")
    signups.add_rows([{"email": "ada@example.com"}])
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import Page, _Object, compact, field, list_all, list_page, parse_time, ref_id
from ._sync import synced

# The most rows one page of a table holds.
MAX_ROWS_PAGE = 10_000


async def _filters(workflow: Any, organization_id: Optional[str]) -> Dict[str, Any]:
    return {"workflow_id": await ref_id(workflow), "organization_id": organization_id}


class WorkflowFile(_Object):
    """A file one of your workflows keeps: what a step or an interface uploaded or
    produced. ``url`` reads it until ``url_expires_at``; list again for a fresh
    one. Tables are apart (``WorkflowTable``).

    You read the files of each workflow ``Workflow.get`` reads: your account's
    own, those shared with it, and the ones its agents run on. They're the
    account's: acting for one of your users, it's refused. An app's own code reads
    only those of a workflow its code made, named with ``workflow``."""

    _repr_keys = ("id", "name")

    id: str = field("id")
    name: str = field("name")
    workflow: Dict[str, Any] = field("workflow", doc=(
        "The workflow that keeps it: ``{id, name, step_types}``. ``step_types`` is what it's made of, at a glance: "
        "at most four of its step types, its triggers first, then its agents, then the rest in the order it holds "
        "them (``['trigger-cron', 'agent:codex', 'automation-hubspot']``); an agent on a coding harness is "
        "``agent:<harness>``. Only step types and harness names, never a step's settings."))
    access: str = field("access", doc=(
        "Your account's access to that workflow: ``owner``, ``editor`` or ``viewer``. Deleting takes owner or "
        "editor."))
    step_id: Optional[str] = field("step_id", doc="The step that keeps it, when one does.")
    type: str = field("type", doc="What it holds: ``image``, ``video``, ``audio``, ``document`` or ``file``.")
    mime_type: Optional[str] = field("mime_type")
    size_bytes: int = field("size_bytes")
    url: Optional[str] = field("url", doc=(
        "A link that reads the file until ``url_expires_at`` (an hour after it's listed), naming nothing of where "
        "it's stored: a picture, PDF, sound or video opens in place, anything else downloads. ``None`` for a file "
        "with nothing stored yet."))
    url_expires_at: Any = field("url_expires_at", parse_time)
    upload_url: Optional[str] = field("upload_url", doc=(
        "Only on a file ``create`` made: where its bytes go, in one PUT whose ``Content-Type`` is its ``mime_type`` "
        "and whose length is its ``size_bytes``, until ``upload_expires_at``."))
    upload_expires_at: Any = field("upload_expires_at", parse_time)
    permanent_url: Optional[str] = field("permanent_url", doc=(
        "Only on a file ``create`` made: where it reads for good once uploaded, which a step or a message may "
        "carry. Anyone holding it reads the file."))
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time)

    # Workflow routes are account-level.
    def _call_scope(self) -> Any:
        return None

    @classmethod
    def from_id(cls, file_id: str, *, client: Optional[Client] = None) -> "WorkflowFile":
        """A handle to one of your workflows' files by id: nothing is read (``delete()`` it, or
        ``get`` it to read it).

        Returns:
            The ``WorkflowFile``, its fields read only by ``get``.

        Usage::

            noclick.WorkflowFile.from_id("6f1c...").delete()
        """
        return cls._new(hints={"id": file_id}, client=client, user=None)

    @synced
    @classmethod
    async def get(cls, file_id: str, *, client: Optional[Client] = None) -> "WorkflowFile":
        """One of your workflows' files by id, as ``list`` shows it.

        Returns:
            The ``WorkflowFile``, its ``url`` good for an hour.

        Usage::

            menu = noclick.WorkflowFile.get("6f1c...")
            print(menu.name, menu.url)
        """
        raw = await resolve_client(client).request(
            "GET", f"/v1/workflows/files/{quote(file_id, safe='')}", user=None)
        return cls._new(raw=raw, client=client, user=None)

    @synced
    @classmethod
    async def create(
        cls, workflow: Any, name: str, *, size_bytes: int, mime_type: Optional[str] = None,
        step_id: Optional[str] = None, type: Optional[str] = None, client: Optional[Client] = None,
    ) -> "WorkflowFile":
        """Make a file of ``workflow`` (a ``Workflow`` or its id) to upload: put its bytes to
        ``upload_url`` in one PUT. ``size_bytes`` is at most 100 MB; ``type`` (``image``,
        ``video``, ``audio``, ``document``, ``file``) is read from ``mime_type`` when left out.
        Takes edit access to the workflow.

        Returns:
            The ``WorkflowFile`` with its ``upload_url`` and ``permanent_url``.

        Usage::

            data = open("menu.pdf", "rb").read()
            menu = noclick.WorkflowFile.create(noclick.Workflow.from_name("Cafe site"), "menu.pdf",
                                               size_bytes=len(data), mime_type="application/pdf")
            httpx.put(menu.upload_url, content=data, headers={"Content-Type": "application/pdf"})
        """
        workflow_id = await ref_id(workflow)
        raw = await resolve_client(client).request(
            "POST", f"/v1/workflows/{quote(str(workflow_id), safe='')}/files", user=None,
            json={"name": name, "size_bytes": size_bytes, **compact(mime_type=mime_type, step_id=step_id, type=type)})
        return cls._new(raw=raw, client=client, user=None)

    @synced
    @classmethod
    async def list(
        cls, *, workflow: Any = None, organization_id: Optional[str] = None, limit: Optional[int] = None,
        client: Optional[Client] = None,
    ) -> List["WorkflowFile"]:
        """The files your workflows keep, most recently changed first: every
        workflow ``Workflow.get`` reads, or one (``workflow``, a ``Workflow`` or
        its id). An app's own code names a workflow its code made.

        Returns:
            Every file, fetched page by page (or the first ``limit``), each with a link good for an hour.

        Usage::

            intake = noclick.Workflow.from_name("Order intake")
            for file in noclick.WorkflowFile.list(workflow=intake):
                print(file.name, file.workflow["name"], file.url)
        """
        return await list_all(
            "/v1/workflows/files", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params=await _filters(workflow, organization_id), user=None, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, workflow: Any = None, organization_id: Optional[str] = None, cursor: Optional[str] = None,
        limit: Optional[int] = None, client: Optional[Client] = None,
    ) -> Page:
        """One page of the files your workflows keep; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the files and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.WorkflowFile.list_page(organization_id="none", limit=25)
            print([file.name for file in page.data])
        """
        return await list_page(
            "/v1/workflows/files", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params=await _filters(workflow, organization_id), user=None, cursor=cursor, limit=limit, client=client,
        )

    @synced
    async def delete(self) -> None:
        """Delete the file for good: its record and what it stored, with no
        trash to restore it from. A step that reads it by its id finds nothing
        there. Takes edit access to its workflow, never one of your agents runs on
        (``noclick.PermissionDenied`` otherwise: change that through the agent).

        Usage::

            for file in noclick.WorkflowFile.list(workflow=noclick.Workflow.from_name("Order intake")):
                if file.name.endswith(".tmp"):
                    file.delete()
        """
        await self._request("DELETE", f"/v1/workflows/files/{quote(str(self._known('id')), safe='')}")


@dataclass(frozen=True)
class TableRow:
    """One row of a table: its ``id``, its position (``index``, from 0 in the
    order rows were added) and its ``data``, the object as it was written."""

    id: str
    index: int
    data: Dict[str, Any]
    created_at: Any
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "TableRow":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("id") or "", int(raw.get("index") or 0), dict(raw.get("data") or {}),
                   parse_time(raw.get("created_at")), raw)


@dataclass(frozen=True)
class RowsPage(Page):
    """One page of a table's rows; pass ``next_cursor`` back as ``cursor`` for
    the next (None = the last page). ``total_count`` is how many rows the table
    holds."""

    total_count: int = 0


class WorkflowTable(_Object):
    """A table one of your workflows keeps rows in (a Table step's, an
    interface's). Read its rows with ``rows()``, never by querying the database
    it names (``database_id``): how a workflow lays its tables out there may
    change. You read the tables of the workflows you read their files of
    (``WorkflowFile``)."""

    _repr_keys = ("id", "name")

    id: str = field("id")
    name: str = field("name")
    workflow: Dict[str, Any] = field("workflow", doc=(
        "The workflow that keeps it: ``{id, name, step_types}``. ``step_types`` is what it's made of, at a glance: "
        "at most four of its step types, its triggers first, then its agents, then the rest in the order it holds "
        "them (``['trigger-cron', 'agent:codex', 'automation-hubspot']``); an agent on a coding harness is "
        "``agent:<harness>``. Only step types and harness names, never a step's settings."))
    access: str = field("access", doc=(
        "Your account's access to that workflow: ``owner``, ``editor`` or ``viewer``. Deleting takes owner or "
        "editor."))
    step_id: Optional[str] = field("step_id", doc="The step that keeps it, when one does.")
    row_count: Optional[int] = field("row_count", doc="How many rows it holds.")
    database_id: Optional[str] = field("database_id", doc=(
        "The database of your account's its rows are kept in (``noclick.Database.from_id``); ``None`` until they "
        "move there."))
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time)

    # Workflow routes are account-level.
    def _call_scope(self) -> Any:
        return None

    def _path(self, suffix: str = "") -> str:
        return f"/v1/workflows/tables/{quote(str(self._known('id')), safe='')}{suffix}"

    @classmethod
    def from_id(cls, table_id: str, *, client: Optional[Client] = None) -> "WorkflowTable":
        """A handle to one of your workflows' tables by id: nothing is read (its rows, or
        ``delete()`` it).

        Returns:
            The ``WorkflowTable``.

        Usage::

            noclick.WorkflowTable.from_id("8a2e...").delete()
        """
        return cls._new(hints={"id": table_id}, client=client, user=None)

    @synced
    @classmethod
    async def create(cls, workflow: Any, name: str, *, step_id: Optional[str] = None,
                     client: Optional[Client] = None) -> "WorkflowTable":
        """Make an empty table of ``workflow`` (a ``Workflow`` or its id), as an interface or a
        Table step does. Takes edit access to the workflow.

        Returns:
            The new ``WorkflowTable``.

        Usage::

            signups = noclick.WorkflowTable.create(noclick.Workflow.from_name("Signups"), "Signups")
            signups.add_rows([{"email": "ada@example.com"}])
        """
        workflow_id = await ref_id(workflow)
        raw = await resolve_client(client).request(
            "POST", f"/v1/workflows/{quote(str(workflow_id), safe='')}/tables", user=None,
            json={"name": name, **compact(step_id=step_id)})
        return cls._new(raw=raw, client=client, user=None)

    @synced
    async def add_rows(self, rows: List[Dict[str, Any]]) -> int:
        """Add ``rows`` at its end, in order, each an object of at most 1 MB as JSON; more than
        10,000 go in as several calls. Takes edit access to its workflow.

        Returns:
            How many rows went in.

        Usage::

            [signups] = noclick.WorkflowTable.list(workflow=noclick.Workflow.from_name("Signups"))
            signups.add_rows([{"email": "ada@example.com"}, {"email": "grace@example.com"}])
        """
        added = 0
        for start in range(0, len(rows), MAX_ROWS_PAGE):
            done = await self._request("POST", self._path("/rows"), json={"rows": rows[start:start + MAX_ROWS_PAGE]})
            added += int((done or {}).get("added") or 0)
        return added

    @synced
    async def update_row(self, row_id: str, data: Dict[str, Any]) -> None:
        """Replace one row's data with ``data``. Takes edit access to its workflow.

        Usage::

            [signups] = noclick.WorkflowTable.list(workflow=noclick.Workflow.from_name("Signups"))
            first = signups.rows(limit=1)[0]
            signups.update_row(first.id, {**first.data, "confirmed": True})
        """
        await self._request("PATCH", self._path(f"/rows/{quote(row_id, safe='')}"), json={"data": data})

    @synced
    async def remove_rows(self, row_ids: List[str]) -> int:
        """Take rows out by id, for good; one it doesn't hold is passed by. Takes edit access to
        its workflow.

        Returns:
            How many rows went.

        Usage::

            [signups] = noclick.WorkflowTable.list(workflow=noclick.Workflow.from_name("Signups"))
            signups.remove_rows([row.id for row in signups.rows() if not row.data.get("email")])
        """
        removed = 0
        for start in range(0, len(row_ids), MAX_ROWS_PAGE):
            done = await self._request("POST", self._path("/rows/remove"),
                                       json={"row_ids": row_ids[start:start + MAX_ROWS_PAGE]})
            removed += int((done or {}).get("removed") or 0)
        return removed

    @synced
    @classmethod
    async def list(
        cls, *, workflow: Any = None, organization_id: Optional[str] = None, limit: Optional[int] = None,
        client: Optional[Client] = None,
    ) -> List["WorkflowTable"]:
        """The tables your workflows keep, most recently changed first: every
        workflow ``Workflow.get`` reads, or one (``workflow``, a ``Workflow`` or
        its id). An app's own code names a workflow its code made.

        Returns:
            Every table, fetched page by page (or the first ``limit``).

        Usage::

            for table in noclick.WorkflowTable.list(workflow=noclick.Workflow.from_name("Signups")):
                print(table.name, table.row_count)
        """
        return await list_all(
            "/v1/workflows/tables", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params=await _filters(workflow, organization_id), user=None, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, workflow: Any = None, organization_id: Optional[str] = None, cursor: Optional[str] = None,
        limit: Optional[int] = None, client: Optional[Client] = None,
    ) -> Page:
        """One page of the tables your workflows keep; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the tables and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.WorkflowTable.list_page(limit=25)
            print([table.name for table in page.data])
        """
        return await list_page(
            "/v1/workflows/tables", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params=await _filters(workflow, organization_id), user=None, cursor=cursor, limit=limit, client=client,
        )

    @synced
    async def rows_page(self, *, cursor: Optional[str] = None, limit: Optional[int] = None) -> RowsPage:
        """One page of its rows in the order they were added (``limit``, 1 to
        10,000; 100 when left out); pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds each ``TableRow``, whose ``next_cursor`` is ``None`` on the last page and
            whose ``total_count`` is how many rows the table holds.

        Usage::

            [signups] = noclick.WorkflowTable.list(workflow=noclick.Workflow.from_name("Signups"))
            page = signups.rows_page(limit=500)
            print([row.data["email"] for row in page.data])
        """
        page = await resolve_client(self._client).request(
            "GET", self._path("/rows"), params={"cursor": cursor, "limit": limit}, user=None) or {}
        return RowsPage([TableRow._from(row) for row in page.get("data") or []], page.get("next_cursor") or None,
                        int(page.get("total_count") or 0))

    @synced
    async def rows(self, *, limit: Optional[int] = None) -> List[TableRow]:
        """Its rows in the order they were added.

        Returns:
            Every row, read 10,000 at a time (or the first ``limit``).

        Usage::

            [signups] = noclick.WorkflowTable.list(workflow=noclick.Workflow.from_name("Signups"))
            emails = [row.data["email"] for row in signups.rows()]
        """
        found: List[TableRow] = []
        cursor = None
        while True:
            size = MAX_ROWS_PAGE if limit is None else min(limit - len(found), MAX_ROWS_PAGE)
            page = await self.rows_page.aio(cursor=cursor, limit=size)
            found.extend(page.data)
            if page.next_cursor is None or (limit is not None and len(found) >= limit):
                return found if limit is None else found[:limit]
            cursor = page.next_cursor

    @synced
    async def delete(self) -> None:
        """Delete the table and every row in it for good, with no trash to
        restore it from. A step or an interface that reads or adds to it fails
        on its next run. Takes edit access to its workflow, never one of your
        agents runs on (``noclick.PermissionDenied`` otherwise).

        Usage::

            [scratch] = noclick.WorkflowTable.list(workflow=noclick.Workflow.from_name("Scratch"))
            scratch.delete()
        """
        await self._request("DELETE", self._path())


class AgentStepWorkspace(_Object):
    """One of your conversations with an agent step of a workflow, as a place
    its files are kept: what ``Step.workspace(conversation)`` reads. You list
    those of your own conversations with the agent steps of every workflow
    ``Workflow.get`` reads (never a share link's visitors', nor an agent's
    workflow: an agent keeps one workspace, ``agent.workspace()``). They're
    your people's, never one of your users': acting for one, it's refused."""

    _repr_keys = ("step_id", "conversation")

    workflow: Dict[str, Any] = field("workflow", doc=(
        "The workflow the step is in: ``{id, name, step_types}``, as ``WorkflowFile.workflow`` names it."))
    step_id: str = field("step_id")
    step_name: str = field("step_name", doc="The agent step's name in the app.")
    model: Optional[str] = field("model", doc="The model the conversation last ran on.")
    conversation: str = field("conversation", doc="The conversation, as ``Step.workspace`` takes it.")
    title: str = field("title")
    last_activity: Any = field("last_activity", parse_time)

    # Workflow routes are account-level.
    def _call_scope(self) -> Any:
        return None

    @synced
    @classmethod
    async def list(
        cls, *, organization_id: Optional[str] = None, limit: Optional[int] = None, client: Optional[Client] = None,
    ) -> List["AgentStepWorkspace"]:
        """Your conversations' workspaces with agent steps, most recently active first, as Resources lists them;
        ``organization_id`` narrows to a team workspace's workflows (``"none"``: those in no workspace).

        Returns:
            Each one (or the first ``limit``).

        Usage::

            for place in noclick.AgentStepWorkspace.list():
                print(place.step_name, place.title, [f.path for f in place.files().files])
        """
        return await list_all(
            "/v1/workflows/workspaces", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params={"organization_id": organization_id}, user=None, limit=limit, client=client,
        )

    @synced
    async def files(self) -> Any:
        """Its files, as ``Step.workspace(conversation)`` reads them.

        Returns:
            The ``StepWorkspace``: its ``files``, and an ``upload_url`` when you may change the workflow.

        Usage::

            [place] = noclick.AgentStepWorkspace.list(limit=1)
            for file in place.files().files:
                print(file.path, file.url)
        """
        from .workflow import Workflow

        step = Workflow.from_id(str(self._known("workflow")["id"]), client=self._client).step(self._known("step_id"))
        return await step.workspace.aio(self._known("conversation"))
