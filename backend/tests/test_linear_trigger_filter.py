"""Tests for LinearNode.filter_trigger_payload granular action filtering."""
import pytest

from nodes.linear_node import LinearNode


def test_filter_matches_correct_type_and_action():
    payload = {"type": "Issue", "action": "create", "data": {}}
    assert LinearNode.filter_trigger_payload(payload, {"operation": "on_issue_created"}) is True


def test_filter_rejects_wrong_action():
    payload = {"type": "Issue", "action": "update", "data": {}}
    assert LinearNode.filter_trigger_payload(payload, {"operation": "on_issue_created"}) is False


def test_filter_rejects_wrong_type():
    payload = {"type": "Comment", "action": "create", "data": {}}
    assert LinearNode.filter_trigger_payload(payload, {"operation": "on_issue_created"}) is False


def test_filter_delete_uses_remove_action():
    """Linear uses 'remove' for deletions, not 'delete'."""
    payload = {"type": "Issue", "action": "remove", "data": {}}
    assert LinearNode.filter_trigger_payload(payload, {"operation": "on_issue_deleted"}) is True


def test_filter_delete_rejects_wrong_action():
    payload = {"type": "Issue", "action": "delete", "data": {}}  # wrong — Linear uses "remove"
    assert LinearNode.filter_trigger_payload(payload, {"operation": "on_issue_deleted"}) is False


def test_filter_comment_created():
    payload = {"type": "Comment", "action": "create", "data": {}}
    assert LinearNode.filter_trigger_payload(payload, {"operation": "on_comment_created"}) is True


def test_filter_project_updated():
    payload = {"type": "Project", "action": "update", "data": {}}
    assert LinearNode.filter_trigger_payload(payload, {"operation": "on_project_updated"}) is True


def test_filter_passthrough_for_non_trigger_op():
    """Non-trigger operations should always pass (return True)."""
    payload = {"type": "Issue", "action": "create"}
    assert LinearNode.filter_trigger_payload(payload, {"operation": "list_issues"}) is True


def test_filter_handles_missing_payload_fields():
    """Missing action/type should not raise, should return False."""
    assert LinearNode.filter_trigger_payload({}, {"operation": "on_issue_created"}) is False


def test_filter_handles_none_config():
    """None config should not raise."""
    payload = {"type": "Issue", "action": "create"}
    assert LinearNode.filter_trigger_payload(payload, None) is True  # no op match → pass through
