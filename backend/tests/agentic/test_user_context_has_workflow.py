"""Regression tests for the resume-after-ask "no workflow open" bug (B1).

When the user answered an <ask/>, the resume path built ``user_context`` as
``{'workflow_id': ...}`` without ``has_workflow``. ``_build_user_context`` then
fell through to "The user does NOT have a workflow open", and the brain re-added
nodes it had already created. The fix derives ``has_workflow`` from the presence
of a ``workflow_id`` when the flag is absent, while an explicit ``False`` still
wins.
"""

from coder.workflow.agentic.prompts import _build_user_context

_OPEN = "open. Add nodes directly"
_NOT_OPEN = "does NOT have a workflow open"


def test_resume_context_without_flag_treats_workflow_as_open():
    # The resume-after-ask path passes only workflow_id (no has_workflow).
    ctx = _build_user_context({"workflow_id": "wf-1"})
    assert _OPEN in ctx
    assert _NOT_OPEN not in ctx


def test_explicit_has_workflow_true_is_open():
    ctx = _build_user_context({"workflow_id": "wf-1", "has_workflow": True})
    assert _OPEN in ctx
    assert _NOT_OPEN not in ctx


def test_no_workflow_id_is_not_open():
    ctx = _build_user_context({"inner_tab": "canvas"})
    assert _NOT_OPEN in ctx
    assert _OPEN not in ctx


def test_explicit_false_wins_over_workflow_id():
    # An explicit has_workflow=False must be honored even with a workflow_id —
    # the derivation only fills an *absent* flag, it never overrides intent.
    ctx = _build_user_context({"workflow_id": "wf-1", "has_workflow": False})
    assert _NOT_OPEN in ctx
    assert _OPEN not in ctx
