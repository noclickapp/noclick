"""Step types: every kind of step a workflow can hold, NoClick's own (triggers,
agents, conditions, loops, interfaces, tables, code) and every integration's,
with the settings each takes.

    for kind in noclick.step_types("send an email", limit=3):
        print(kind.type, kind.label, [op.name for op in kind.operations][:3])
    gmail = noclick.step_type("automation-gmail")
    print(gmail.schema["properties"]["config"])

A step's ``type`` is what ``workflow.add_step`` takes; ``operations`` what its
``operation=`` takes; its ``schema`` the settings ``settings=`` takes, as the
app's canvas draws a step's form from it. ``Connection.integrations()`` is the
catalog of services an account connects; this one holds every step.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._client import Client, path_segment, resolve_client
from ._object import paginate
from ._sync import synced


@dataclass(frozen=True)
class StepTypeOperation:
    """One operation a step of the type runs: what ``operation=`` takes."""

    name: str
    label: Optional[str]
    #: What it does; ``None`` in a listing (``step_type()`` reads it).
    description: Optional[str]
    #: Whether it starts runs (a trigger operation, ``x-is-trigger``) rather than acting when a run reaches it.
    trigger: bool
    #: Whether running it needs an account connected to the step: False when it runs on NoClick's key with no
    #: account (web search, public data) or the type takes none; True otherwise, also when the need depends on its
    #: settings.
    needs_account: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "StepTypeOperation":
        return cls(raw["name"], raw.get("label"), raw.get("description"), bool(raw["trigger"]),
                   bool(raw["needs_account"]), raw)


@dataclass(frozen=True)
class StepTypeConnection:
    """The accounts a step of the type connects to (``step.set_connection``)."""

    #: Whether every operation needs one, so a step of it can't run without.
    needed: bool
    #: Its name in ``Connection.integrations()`` (``integration=`` when you make a connection for it), or ``None`` for
    #: a step whose account isn't connected there (an agent's model key).
    integration: Optional[str]
    #: The credential types its settings take, as a step's ``connections`` names them.
    credential_types: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["StepTypeConnection"]:
        if not raw:
            return None
        return cls(bool(raw["needed"]), raw.get("integration"), list(raw.get("credential_types") or []), raw)


@dataclass(frozen=True)
class StepType:
    """A kind of step a workflow can hold: one of ``step_types()``."""

    #: What ``workflow.add_step`` takes, as a workflow's graph names it: ``automation-slack``, ``agent``,
    #: ``trigger-cron``.
    type: str
    #: Its name in the app (``Slack``, ``AI Agent``, ``Schedule``).
    label: Optional[str]
    description: Optional[str]
    #: The section the app lists an integration under (``communication``, ``crm-sales``); ``None`` for NoClick's own.
    category: Optional[str]
    #: What a step of it can be in a workflow: ``trigger`` (a run starts from it: ``trigger`` below, or one of its
    #: operations) and ``tool`` (an agent uses its operations as tools).
    kinds: List[str]
    #: Whether a step of it starts runs whatever its operation (a trigger step: a schedule, a webhook, a form).
    trigger: bool
    #: Each operation once, in the order the app lists them; empty for a type that has none (``trigger-run``).
    operations: List[StepTypeOperation]
    #: The accounts it connects to; ``None`` for a type whose settings take none.
    connection: Optional[StepTypeConnection]
    #: Why its service is gone and since when (``reason``, ``since``), or ``None`` while it works. A listing leaves
    #: retired types out; ``step_type()`` still reads one, since a step saved on it still loads and runs.
    retired: Optional[Dict[str, Any]]
    #: The JSON Schema of a step's settings, as the app's canvas draws its form from it (``properties.config``, a
    #: member per operation where it has several, with the canvas's ``x-`` and ``ui:`` extensions). ``None`` in a
    #: listing, and for a type that takes no settings.
    schema: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "StepType":
        return cls(raw["type"], raw.get("label"), raw.get("description"), raw.get("category"),
                   list(raw.get("kinds") or []), bool(raw["trigger"]),
                   [StepTypeOperation._from(op) for op in raw.get("operations") or []],
                   StepTypeConnection._from(raw.get("connection")), raw.get("retired"), raw.get("schema"), raw)


@synced
async def step_types(
    query: Optional[str] = None, *, kind: Optional[str] = None, limit: Optional[int] = None,
    client: Optional[Client] = None,
) -> List[StepType]:
    """Every kind of step a workflow can hold, NoClick's own first, then the
    integrations most used first; with ``query``, those it finds by name or by
    what they do, the best first, as the app's builder searches.
    ``kind="trigger"`` keeps the types a run starts from (a trigger step, or one
    with a trigger operation), ``kind="tool"`` those an agent uses as its tools;
    any other raises ``noclick.InvalidRequest``. A listing leaves out each
    operation's description and the settings schema: ``step_type()`` reads them.
    Needs the ``workflows`` scope.

    Returns:
        Each type's ``type`` (what ``workflow.add_step`` takes), ``label``, ``kinds``, ``operations`` (each
        with whether it's a ``trigger`` and ``needs_account``) and ``connection``, fetched page by page
        (or the first ``limit``).

    Usage:
        Find the step for a job, and add it::

            [send] = noclick.step_types("send an email", limit=1)
            brief = noclick.Workflow.from_name("Morning brief")
            brief.add_step(send.type, operation=send.operations[0].name)

        Or every way a run can start::

            for kind in noclick.step_types(kind="trigger"):
                starts = [op.name for op in kind.operations if op.trigger] or ["(the step itself)"]
                print(kind.type, starts)
    """
    rows = await paginate(resolve_client(client), "/v1/step_types", params={"q": query, "kind": kind}, user=None,
                          limit=limit)
    return [StepType._from(row) for row in rows]


@synced
async def step_type(name: str, *, client: Optional[Client] = None) -> StepType:
    """One step type, each operation with its ``description``, and its
    ``schema``: what a step's ``settings`` take, as the app's canvas draws its
    form from it. ``name`` is the type as a workflow's graph names it
    (``automation-gmail``, ``agent``); an unknown one raises
    ``noclick.NotFound`` naming the nearest. Needs the ``workflows`` scope.

    Returns:
        The type, with its ``schema`` (``None`` for a type that takes no settings).

    Usage::

        gmail = noclick.step_type("automation-gmail")
        send = next(op for op in gmail.operations if op.name == "send_email_message")
        print(send.description, gmail.connection.credential_types)
        print(list(gmail.schema["$defs"]))
    """
    raw = await resolve_client(client).request("GET", f"/v1/step_types/{path_segment(name)}", user=None)
    return StepType._from(raw)


@dataclass(frozen=True)
class StepOutputShape:
    """What a step of a type outputs, as your account's own runs and events of it showed it
    (and those of people in a workspace with you), never another account's: ``shape``, its
    fields' names and types, with ``suggested_refs``, the few references worth offering first
    (``None`` until they're made). ``shape`` is ``None`` until your first run or event of it."""

    type: str
    operation: str
    shape: Optional[Dict[str, Any]]
    suggested_refs: Optional[List[Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "StepOutputShape":
        refs = raw.get("suggested_refs")
        return cls(raw["type"], raw["operation"], raw.get("shape"), list(refs) if isinstance(refs, list) else None,
                   raw)


@synced
async def step_output_shape(name: str, *, operation: Optional[str] = None,
                            client: Optional[Client] = None) -> StepOutputShape:
    """What a step of type ``name`` outputs (its ``operation``'s, for a type with several),
    learned from your account's own runs: the fields a later step's settings can reference,
    as the app's canvas offers them. Needs the ``workflows`` scope.

    Returns:
        The ``StepOutputShape``; an unknown type raises ``noclick.NotFound`` naming the nearest.

    Usage::

        found = noclick.step_output_shape("automation-hubspot", operation="get_contact")
        print(list((found.shape or {}).get("properties", {})))
    """
    raw = await resolve_client(client).request(
        "GET", f"/v1/step_types/{path_segment(name)}/output_shape", params={"operation": operation}, user=None)
    return StepOutputShape._from(raw)
