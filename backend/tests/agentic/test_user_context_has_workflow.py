"""Regression tests for the resume-after-ask "no workflow open" bug (B1).

When the user answered an <ask/>, the resume path built ``user_context`` as
``{'workflow_id': ...}`` without ``has_workflow``. The user context then said no
workflow was open, and the brain re-added nodes it had already created. The fix
derives ``has_workflow`` from the presence of a ``workflow_id`` when the flag is
absent, while an explicit ``False`` still wins.

These hold for every prompt pack: they compare contexts rather than read a
pack's wording.
"""

from coder.workflow.agentic.prompts import build_user_context


def _open():
    return build_user_context({"workflow_id": "wf-1", "has_workflow": True})


def _not_open():
    return build_user_context({"workflow_id": "wf-1", "has_workflow": False})


def test_open_and_not_open_read_differently():
    assert _open() != _not_open()
    assert "wf-1" in _open()


def test_resume_context_without_flag_treats_workflow_as_open():
    # The resume-after-ask path passes only workflow_id (no has_workflow).
    assert build_user_context({"workflow_id": "wf-1"}) == _open()


def test_no_workflow_id_is_not_open():
    assert build_user_context({"inner_tab": "canvas"}) == build_user_context(
        {"has_workflow": False, "inner_tab": "canvas"}
    )
    assert "wf-1" not in build_user_context({"inner_tab": "canvas"})


def test_explicit_false_wins_over_workflow_id():
    # An explicit has_workflow=False must be honored even with a workflow_id —
    # the derivation only fills an *absent* flag, it never overrides intent.
    assert _not_open() == build_user_context({"has_workflow": False})
