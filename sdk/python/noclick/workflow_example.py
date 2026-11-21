"""NoClick's example workflows: the ones its builder studies before it builds,
each what it's for, guidance text, a workflow, or both. The same for every
account.

    for example in noclick.workflow_examples("triage support email", limit=3):
        print(example.name, example.step_types)
    example = noclick.workflow_example(example.id)
    print(example.text, [node["type"] for node in example.graph["nodes"]])
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._client import Client, path_segment, resolve_client
from ._object import paginate, parse_time
from ._sync import synced


@dataclass(frozen=True)
class WorkflowExample:
    """One of NoClick's example workflows: one of ``workflow_examples()``."""

    id: str
    name: str
    #: What it's for, and when it applies.
    description: Optional[str]
    #: Whether it holds guidance text, and a workflow.
    has_text: bool
    has_workflow: bool
    #: What its workflow is made of, at a glance, as ``Workflow.step_types`` says it: its triggers first, then its
    #: agents, then the rest.
    step_types: List[str]
    updated_at: Any
    #: Its guidance, in Markdown; ``None`` in a listing (``workflow_example()`` reads it).
    text: Optional[str]
    #: Its workflow as ``workflow.graph()`` reads a workflow's (``nodes``, each with its ``type`` and ``config``,
    #: and ``edges``), without the connections or test outputs of the account it was made in, never a secret;
    #: ``None`` in a listing and for one that's guidance only.
    graph: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "WorkflowExample":
        return cls(raw["id"], raw["name"], raw.get("description"), bool(raw.get("has_text")),
                   bool(raw.get("has_workflow")), list(raw.get("step_types") or []), parse_time(raw.get("updated_at")),
                   raw.get("text"), raw.get("graph"), raw)


@synced
async def workflow_examples(
    query: Optional[str] = None, *, limit: Optional[int] = None, client: Optional[Client] = None,
) -> List[WorkflowExample]:
    """NoClick's own example workflows, the ones its builder studies before it
    builds, most recently changed first; with ``query``, the ones it finds by
    name, what they're for and their text, the best first. A listing leaves
    each one's text and workflow out: ``workflow_example()`` reads them. Needs
    the ``workflows`` scope.

    Returns:
        Each example's ``name``, ``description``, whether it has guidance ``text`` and a workflow, and what that's
        made of (``step_types``), fetched page by page (or the first ``limit``).

    Usage:
        Find the examples for a job, and read the best one whole::

            [best] = noclick.workflow_examples("post new form answers to Slack", limit=1)
            example = noclick.workflow_example(best.id)
            print(example.text)
            for node in example.graph["nodes"]:
                print(node["type"], node["config"].get("operation"))
    """
    rows = await paginate(resolve_client(client), "/v1/workflow_examples", params={"q": query}, user=None,
                          limit=limit)
    return [WorkflowExample._from(row) for row in rows]


@synced
async def workflow_example(example_id: str, *, client: Optional[Client] = None) -> WorkflowExample:
    """One of NoClick's example workflows whole: its guidance ``text`` and its
    workflow's ``graph``. An id that names none raises ``noclick.NotFound``.
    Needs the ``workflows`` scope.

    Returns:
        The example, with its ``text`` and ``graph`` (each ``None`` where it has none).

    Usage::

        example = noclick.workflow_example("6f1c2e9a-3b7d-4f0e-9a51-2d8c4b7e1a03")
        print(example.description, example.step_types)
    """
    raw = await resolve_client(client).request("GET", f"/v1/workflow_examples/{path_segment(example_id)}", user=None)
    return WorkflowExample._from(raw)
