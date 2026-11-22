"""The workflow builder, made and run with the NoClick SDK: nothing here that your own code couldn't do with a key.

``ensure`` makes the account's builder (or returns the one it has); ``build`` hands it one workflow and what to do,
waits for its reply, then reads the workflow's own facts and sends the builder back when they say the build isn't
done: a step it left would fail at run time, or nothing was built (``definition.send_back``). NoClick's hosted platform runs the same loop from the same definition.

    import noclick
    from noclick_builder import agent as builder

    brief = noclick.Workflow.create("Morning brief")           # an empty workflow
    built = builder.build(brief, "Every weekday at 8, email me today's calendar.")
    print(built.summary)
    print(built.readiness["status"], built.readiness["issues"])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import noclick

from . import definition

@dataclass
class Built:
    """What a build came to: the builder's own words, and beside them the workflow's facts, which no model wrote."""

    workflow_id: str
    #: What the builder said it did.
    summary: str
    #: Whether the workflow's definition moved since the build began.
    built: bool
    #: The version the workflow ended on.
    version: Optional[int]
    #: Whether it can run, and what's in the way: ``status``, ``issues``, ``warnings``, ``unverified``.
    readiness: Dict[str, Any]
    #: What it was sent back for, in order: ``rejected`` (settings a run would refuse) or ``nothing`` (nothing built).
    sent_back: List[str] = field(default_factory=list)
    #: Each reply the builder gave, the last one last.
    replies: List[Any] = field(default_factory=list, repr=False)


def sdk_tools() -> List[Any]:
    """The builder's tools, as SDK objects: NoClick itself narrowed to what building takes, the account's owner to
    ask and tell, and the web. ``definition.wire_tools()`` is what they serialize to."""
    owner = noclick.Human.owner()
    return [
        noclick.Platform.only(*definition.PLATFORM_GROUPS, *definition.PLATFORM_AREAS),
        owner.only(*definition.OWNER_TOOLS),
        *definition.WEB_TOOLS,
    ]


def ensure(*, instructions: Optional[str] = None, client: Optional[noclick.Client] = None) -> noclick.Agent:
    """The account's builder: made the first time, the one already there after that. Pass ``instructions`` to give
    it your own wording; a builder that exists keeps the instructions it has until you ``update`` it."""
    return noclick.Agent.create(
        definition.NAME,
        allow_existing=True,
        instructions=instructions or definition.instructions(),
        tools=sdk_tools(),
        shell=definition.SHELL,
        client=client,
    )


def _rejected(readiness: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [issue for issue in readiness.get("issues") or [] if issue.get("code") == definition.REJECTED_ISSUE]


def build(workflow: Union[noclick.Workflow, str], instructions: str, *, questions: str = definition.ASK,
          publish: Optional[Dict[str, Any]] = None, timeout: Optional[float] = 1800,
          client: Optional[noclick.Client] = None) -> Built:
    """Have the builder build or change ``workflow`` (a ``Workflow`` or its id) as ``instructions`` say.

    It works in the workflow's own conversation, so a later build reads what earlier ones asked and learned. When
    it asks the account's owner something, its turn waits on their answer (the question reaches them as any agent's
    does) and this call waits with it, up to ``timeout`` seconds a turn. ``questions="assume"`` has it ask nothing.

    Returns the builder's reply and the workflow's facts as they stand once it's done.
    """
    workflow = noclick.Workflow.get(workflow, client=client) if isinstance(workflow, str) else workflow
    builder = ensure(client=client)
    conversation = definition.conversation(workflow.id)
    began = workflow.graph().version

    text = definition.request(workflow.id, instructions, name=workflow.name, questions=questions, publish=publish)
    replies = [builder.message(text, conversation=conversation, timeout=timeout)]
    sent_back: List[str] = []
    while True:
        # The facts, read from the workflow itself.
        now = noclick.Workflow.get(workflow.id, client=client)
        version = workflow.graph().version
        issues = _rejected(now.readiness)
        why = definition.send_back(built=version != began, empty=not now.steps, rejected=issues, sent=sent_back)
        if why is None:
            break
        # It hears exactly what's wrong, in the same conversation, and fixes it.
        sent_back.append(why)
        again = definition.sent_back(issues) if why == definition.REJECTED else (
            definition.NOTHING_BUILT if not now.steps else definition.NOTHING_CHANGED)
        replies.append(builder.message(again, conversation=conversation, timeout=timeout))
    return Built(workflow_id=workflow.id, summary=replies[-1].text, built=version != began, version=version,
                 readiness=now.readiness, sent_back=sent_back, replies=replies)
