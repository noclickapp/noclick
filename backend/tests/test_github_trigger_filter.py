"""Tests for GithubRestNode.filter_trigger_payload granular action filtering."""
from nodes.github_rest_node import GithubRestNode


# ── Issue triggers ─────────────────────────────────────────────────────────────

def test_issue_opened_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "opened"}, {"operation": "on_issue_opened"}) is True

def test_issue_opened_rejects_wrong_action():
    assert GithubRestNode.filter_trigger_payload({"action": "closed"}, {"operation": "on_issue_opened"}) is False

def test_issue_closed_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "closed"}, {"operation": "on_issue_closed"}) is True

def test_issue_labeled_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "labeled"}, {"operation": "on_issue_labeled"}) is True

def test_issue_demilestoned_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "demilestoned"}, {"operation": "on_issue_demilestoned"}) is True


# ── Pull request triggers ──────────────────────────────────────────────────────

def test_pr_opened_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "opened"}, {"operation": "on_pull_request_opened"}) is True

def test_pr_opened_rejects_wrong():
    assert GithubRestNode.filter_trigger_payload({"action": "closed"}, {"operation": "on_pull_request_opened"}) is False

def test_pr_merged_requires_merged_flag():
    """GitHub sends action=closed with merged=true for merges."""
    payload = {"action": "closed", "pull_request": {"merged": True}}
    assert GithubRestNode.filter_trigger_payload(payload, {"operation": "on_pull_request_merged"}) is True

def test_pr_merged_rejects_plain_close():
    """A plain close (not merged) should NOT fire on_pull_request_merged."""
    payload = {"action": "closed", "pull_request": {"merged": False}}
    assert GithubRestNode.filter_trigger_payload(payload, {"operation": "on_pull_request_merged"}) is False

def test_pr_merged_rejects_wrong_action():
    payload = {"action": "opened", "pull_request": {"merged": True}}
    assert GithubRestNode.filter_trigger_payload(payload, {"operation": "on_pull_request_merged"}) is False

def test_pr_closed_fires_on_plain_close():
    """on_pull_request_closed should fire when a PR is closed WITHOUT merging."""
    payload = {"action": "closed", "pull_request": {"merged": False}}
    assert GithubRestNode.filter_trigger_payload(payload, {"operation": "on_pull_request_closed"}) is True

def test_pr_closed_does_not_fire_on_merge():
    """on_pull_request_closed should NOT fire when a PR is merged (action=closed + merged=true)."""
    payload = {"action": "closed", "pull_request": {"merged": True}}
    assert GithubRestNode.filter_trigger_payload(payload, {"operation": "on_pull_request_closed"}) is False

def test_pr_synchronize_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "synchronize"}, {"operation": "on_pull_request_synchronize"}) is True

def test_pr_ready_for_review_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "ready_for_review"}, {"operation": "on_pull_request_ready_for_review"}) is True

def test_pr_review_requested_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "review_requested"}, {"operation": "on_pull_request_review_requested"}) is True

def test_pr_review_request_removed_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "review_request_removed"}, {"operation": "on_pull_request_review_request_removed"}) is True

def test_pr_auto_merge_enabled_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "auto_merge_enabled"}, {"operation": "on_pull_request_auto_merge_enabled"}) is True

def test_pr_auto_merge_disabled_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "auto_merge_disabled"}, {"operation": "on_pull_request_auto_merge_disabled"}) is True


# ── Release triggers ───────────────────────────────────────────────────────────

def test_release_published_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "published"}, {"operation": "on_release_published"}) is True

def test_release_deleted_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "deleted"}, {"operation": "on_release_deleted"}) is True

def test_release_prereleased_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "prereleased"}, {"operation": "on_release_prereleased"}) is True


# ── Star triggers ──────────────────────────────────────────────────────────────

def test_star_created_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "created"}, {"operation": "on_star_created"}) is True

def test_star_deleted_matches():
    assert GithubRestNode.filter_trigger_payload({"action": "deleted"}, {"operation": "on_star_deleted"}) is True

def test_star_created_rejects_deleted():
    assert GithubRestNode.filter_trigger_payload({"action": "deleted"}, {"operation": "on_star_created"}) is False


# ── Pass-through operations ────────────────────────────────────────────────────

def test_on_push_always_passes():
    """Push events have no action field — always passes."""
    assert GithubRestNode.filter_trigger_payload({"ref": "refs/heads/main"}, {"operation": "on_push"}) is True

def test_on_issue_comment_always_passes():
    """Issue comment fires for all comment actions — always passes."""
    assert GithubRestNode.filter_trigger_payload({"action": "created"}, {"operation": "on_issue_comment"}) is True
    assert GithubRestNode.filter_trigger_payload({"action": "deleted"}, {"operation": "on_issue_comment"}) is True


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_non_trigger_op_always_passes():
    """Non-trigger operations are not in _trigger_event_map and should pass through."""
    assert GithubRestNode.filter_trigger_payload({"action": "anything"}, {"operation": "list_repositories"}) is True

def test_missing_action_in_payload_rejects():
    """If the payload has no action field, the filter should reject (return False)."""
    assert GithubRestNode.filter_trigger_payload({}, {"operation": "on_issue_opened"}) is False

def test_none_config_passes():
    """None config → no operation → not a trigger op → pass through."""
    assert GithubRestNode.filter_trigger_payload({"action": "opened"}, None) is True

def test_missing_pull_request_key_in_merged_check():
    """If pull_request key is absent, merged check should not raise."""
    payload = {"action": "closed"}  # no pull_request key
    assert GithubRestNode.filter_trigger_payload(payload, {"operation": "on_pull_request_merged"}) is False

def test_missing_pull_request_key_in_closed_check():
    """If pull_request key is absent in closed check, should not raise."""
    payload = {"action": "closed"}  # no pull_request key → merged=None → not merged → passes closed
    assert GithubRestNode.filter_trigger_payload(payload, {"operation": "on_pull_request_closed"}) is True
