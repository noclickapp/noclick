"""NoClick's workflow builder, defined: an ordinary NoClick agent, nothing private.

Everything here is plain data and text, with no dependency (not even the SDK), so the same definition makes the
builder wherever it runs: ``agent.py`` makes it with the SDK from your own key, and NoClick's hosted platform makes
each account's from this same module. What differs on the hosted platform is only the wording of its instructions,
which NoClick tunes; ``INSTRUCTIONS.md`` here is the plain text that works on its own.

The builder holds no tool of its own. It builds with NoClick's API, through the ``noclick`` tool every agent can be
given (``api_describe`` and ``api_call`` for any operation, ``search`` and ``fetch`` for the docs and the account's
objects), asks the account's owner through the ``human`` tool, and reads the web and its shell like any agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

#: The agent's name: one per account, made the first time it's needed and kept.
NAME = "builder"
#: The line the app shows beside it.
ROLE = "Builds and changes your workflows from what you describe."

#: What it may do on NoClick, as a connected app's grant names it: read, change (build), publish an interface
#: (deploy) and remove a step that holds something a restore can't bring back (delete). Never spend.
PLATFORM_GROUPS = ("read", "build", "deploy", "delete")
#: The parts of the API it reaches (a key's scopes): workflows (their graph, edits, drafts, runs, outputs, test runs,
#: the step catalog and the examples), the account's connections, questions to people, secrets by name, and the
#: operations it waits on.
PLATFORM_AREAS = ("workflows", "credentials", "humans", "secrets", "operations")
#: What it does with the account's owner: tells them what it couldn't do, and asks what it can't decide.
OWNER_TOOLS = ("notify", "ask")
#: The web, to read an API's docs or a page the request names.
WEB_TOOLS = ("search", "fetch")
#: A shell of its own, to look at a URL's real response or shape sample data while it builds.
SHELL = True

#: Whether a build asks the person what it can't decide, or decides and says what it assumed.
ASK, ASSUME = "ask", "assume"

_HERE = Path(__file__).resolve().parent


def instructions() -> str:
    """The builder's instructions as they ship here: the steps of building a workflow, in plain words."""
    return (_HERE / "INSTRUCTIONS.md").read_text(encoding="utf-8").strip()


def conversation(workflow_id: str) -> str:
    """The conversation a workflow's builds share, so a later build reads what an earlier one asked and learned."""
    return f"build:{workflow_id}"


def wire_tools() -> List[Any]:
    """The builder's tools as ``POST /v1/agents`` takes them: what ``agent.sdk_tools()`` serializes to."""
    return [
        *(f"noclick.{name}" for name in (*PLATFORM_GROUPS, *PLATFORM_AREAS)),
        {"human": {"owner": True}, "tools": list(OWNER_TOOLS)},
        *WEB_TOOLS,
    ]


def request(workflow_id: str, instructions: str, *, name: Optional[str] = None, questions: str = ASK,
            publish: Optional[Dict[str, Any]] = None) -> str:
    """The message that asks the builder for one build: which workflow, what to do, and how to treat what it can't
    decide. ``publish``: publish the workflow's interface once the build is done (``{"subdomain": ...}`` to name
    its address)."""
    if questions not in (ASK, ASSUME):
        raise ValueError(f"questions is '{ASK}' or '{ASSUME}'")
    if not (instructions or "").strip():
        raise ValueError("A build needs instructions: what the workflow should do, or what to change.")
    named = f' "{name}"' if name else ""
    lines = [f"Build request for workflow{named} (id {workflow_id}).", "", instructions.strip()]
    if questions == ASSUME:
        lines += ["", "Ask nothing in this build: where you would ask, make the likeliest choice (an account the "
                      "person must connect stays unconnected), and say in your reply what you assumed and what the "
                      "person still needs to do."]
    if publish is not None:
        where = f" at the subdomain {publish['subdomain']}" if publish.get("subdomain") else ""
        lines += ["", f"Once it's built, publish its interface{where}, and give its address in your reply."]
    return "\n".join(lines)


# ── a finished build that goes back to the builder ──────────────────────────
# A reply is the builder's own words. What the workflow is, is read from the workflow: when that says the build
# isn't done, the builder hears exactly what, in the same conversation, before anyone is told it's finished.

#: Why a build goes back: settings a run would refuse (the readiness issue ``invalid_config``), or nothing built.
REJECTED, NOTHING = "rejected", "nothing"
#: The readiness issue a run refuses outright: a step's settings the run engine rejects.
REJECTED_ISSUE = "invalid_config"
#: How many times a build goes back for settings a run would refuse. Nothing built sends it back once.
SEND_BACKS = 2

NOTHING_BUILT = (
    "The workflow has no steps, so nothing your reply describes exists yet. Add the steps, then reply again. What "
    "the person left out is no reason to build nothing: use a sensible default and say which. If the request "
    "genuinely needs no steps, say so, and never say something was built, tested or sent.")
NOTHING_CHANGED = (
    "The workflow is exactly as it was when this request was made, so nothing your reply says you changed has "
    "changed. Make the change now, then reply again. If the request genuinely needs no change (it asked a question, "
    "or the workflow already does it), say which, and never say something was changed, tested or sent.")


def send_back(*, built: Optional[bool], empty: bool, rejected: List[Dict[str, Any]],
              sent: List[str]) -> Optional[str]:
    """Whether a build whose builder just replied goes back to it, and why (``REJECTED`` or ``NOTHING``), from the
    workflow's facts: ``built`` (whether its definition moved since the build began; None when that couldn't be
    read), ``empty`` (it has no steps), ``rejected`` (its readiness issues a run refuses) and ``sent`` (what this
    build already went back for). None: the build is done, and its facts say how it stands."""
    if rejected and sent.count(REJECTED) < SEND_BACKS:
        return REJECTED
    if built is False and NOTHING not in sent:
        return NOTHING
    return None


def sent_back(issues: List[Dict[str, Any]], *, skipped: bool = False) -> str:
    """The message a finished build is sent back with when its workflow holds settings a run would refuse: each
    issue is ``{step, message}``, as the workflow's readiness names them. A value only the person knows is never
    the builder's to make up: it leaves that setting for them (an edit's ``left_for_user``), which is no longer an
    issue here. ``skipped``: the person skipped a question of this build, so it asks for nothing more."""
    listed = "\n".join(f"- {i.get('step')}: {i.get('message')}" for i in issues)
    asking = ("They skipped a question in this build, so don't ask for anything now." if skipped else
              "Don't ask for it now unless nothing else can be built without it.")
    return ("The workflow isn't ready to run: these steps' settings will fail exactly as listed (a run checks them "
            "the same way).\n"
            f"{listed}\n"
            "Fix each one whose value follows from the request, then reply again with what you changed. A setting "
            "whose value only the person knows isn't yours to fix or make up: leave it for them with update_step "
            f"and left_for_user, and name it in your reply. {asking} If one genuinely can't be fixed, say which "
            "and why.")
