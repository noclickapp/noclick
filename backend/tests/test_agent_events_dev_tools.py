"""``resolve_agent_event`` for the dev-tool triggers (GitHub, GitLab, Linear,
Jira, Notion, Trello, Asana, ClickUp, monday.com).

A trigger wired directly into an AI agent delivers its fired output through
``NodeClass.resolve_agent_event(output)``. For these providers the raw payload
is huge (GitHub sends ``repository`` + ``sender`` objects with ~100 keys) and
the base JSON dump buries the one thing the agent needs — the issue, comment,
push or card the event is about. Each override must (a) surface the human
content, (b) never leak the delivery envelope (``_webhook`` headers, secrets),
(c) name a REAL operation of the node with the exact ids to act on, (d) key
the conversation on the issue/PR/MR identity where a thread is natural, and
(e) fall through to the base for any shape it does not recognise.

Fixtures are fictional (``acme-example`` orgs, ``.example`` hosts).
"""
import json
from functools import lru_cache

import pytest

from nodes.asana_node import AsanaNode
from nodes.clickup_node import ClickUpNode
from nodes.github_rest_node import GithubRestNode
from nodes.gitlab_node import GitLabNode
from nodes.jira_node import JiraNode
from nodes.linear_node import LinearNode
from nodes.monday_node import MondayNode
from nodes.notion_node import NotionNode
from nodes.trello_node import TrelloNode

SECRET = "sha256=deadbeefcafe0123"
WEBHOOK = {"id": "wh-1", "method": "POST", "headers": {"x-hub-signature-256": SECRET}, "query_params": {}}
# The manual-run envelope: never a real fire, must not crash, must fall through.
MANUAL_RUN = {"status": "success", "action": "on_event", "data": {"event": "$rageclick", "distinct_id": "u1"}}

ALL_NODES = [GithubRestNode, GitLabNode, LinearNode, JiraNode, NotionNode, TrelloNode, AsanaNode, ClickUpNode, MondayNode]


@lru_cache(maxsize=None)
def _schema_text(node_cls) -> str:
    return json.dumps(node_cls.get_config_schema())


def assert_names_real_operation(node_cls, text: str, *operations: str):
    """The act hint must name operations this node actually exposes."""
    for op in operations:
        assert op in text, f"act hint should name {op}"
        assert f'"{op}"' in _schema_text(node_cls), f"{node_cls.__name__} has no operation {op}"


def assert_clean(ev, *forbidden: str):
    assert isinstance(ev, dict) and ev["text"]
    assert len(ev["text"]) < 4000
    for token in (SECRET, "_webhook", *forbidden):
        assert token not in ev["text"], f"{token!r} leaked into the agent turn"


@pytest.mark.parametrize("node_cls", ALL_NODES, ids=lambda c: c.__name__)
def test_unrecognized_shape_falls_through_to_base(node_cls):
    ev = node_cls.resolve_agent_event(MANUAL_RUN)
    assert ev["conversation_key"] is None
    assert ev["text"].startswith("Event: on_event")
    assert node_cls.resolve_agent_event({"unrelated": "shape"})["text"].lstrip().startswith("{")


# ── GitHub ───────────────────────────────────────────────────────────────────

GH_REPO = {
    "id": 1, "full_name": "acme-example/api", "private": True, "owner": {"login": "acme-example", "id": 3, "avatar_url": "https://avatars.example/3"},
    "html_url": "https://github.example/acme-example/api", "description": "The API", "default_branch": "main",
}
GH_SENDER = {"login": "octo-example", "id": 7, "avatar_url": "https://avatars.example/7", "type": "User"}


def _gh(**payload):
    return {"repository": GH_REPO, "sender": GH_SENDER, "_webhook": WEBHOOK, **payload}


def test_github_issue_opened_surfaces_record_and_keys_on_issue():
    ev = GithubRestNode.resolve_agent_event(_gh(
        action="opened",
        issue={
            "number": 42, "title": "Login broken", "body": "Clicking login returns a 500.", "state": "open",
            "html_url": "https://github.example/acme-example/api/issues/42", "labels": [{"name": "bug"}, {"name": "p1"}],
            "user": {"login": "octo-example"}, "assignees": [{"login": "dev-example"}],
        },
    ))
    assert_clean(ev, "avatar_url", "default_branch")
    text = ev["text"]
    assert text.startswith("GitHub issue opened by octo-example in acme-example/api:")
    assert "Issue #42: Login broken" in text and "Clicking login returns a 500." in text
    assert "- labels: bug, p1" in text and "- assignees: dev-example" in text
    assert "https://github.example/acme-example/api/issues/42" in text
    assert "create_issue_comment with owner=acme-example, repo=api, issue_number=42" in text
    assert_names_real_operation(GithubRestNode, text, "create_issue_comment")
    assert ev["conversation_key"] == "acme-example/api#42"
    assert ev["title"] == "Issue #42: Login broken"


def test_github_issue_comment_on_pr_shares_the_pr_thread():
    ev = GithubRestNode.resolve_agent_event(_gh(
        action="created",
        issue={"number": 7, "title": "Fix auth", "state": "open", "pull_request": {"url": "https://api.example/pulls/7"}, "user": {"login": "dev-example"}},
        comment={"body": "LGTM, one nit.", "html_url": "https://github.example/acme-example/api/pull/7#issuecomment-1", "user": {"login": "octo-example"}},
    ))
    assert_clean(ev)
    assert ev["text"].startswith("GitHub comment created by octo-example on Pull request #7: Fix auth in acme-example/api:")
    assert "LGTM, one nit." in ev["text"]
    assert_names_real_operation(GithubRestNode, ev["text"], "create_issue_comment", "create_pull_request_review")
    assert "pull_number=7" in ev["text"]
    assert ev["conversation_key"] == "acme-example/api#7"


def test_github_pull_request_state_branches_and_long_body_clip():
    ev = GithubRestNode.resolve_agent_event(_gh(
        action="opened",
        pull_request={
            "number": 7, "title": "Fix auth", "body": "x" * 2000, "state": "open", "merged": False, "draft": True,
            "head": {"ref": "fix/auth"}, "base": {"ref": "main"}, "user": {"login": "dev-example"}, "html_url": "https://github.example/acme-example/api/pull/7",
        },
    ))
    assert_clean(ev)
    assert "- draft: yes" in ev["text"] and "- branches: fix/auth → main" in ev["text"]
    assert "[500 more chars]" in ev["text"]
    assert ev["title"] == "Pull request #7: Fix auth"


def test_github_push_lists_commits_without_a_thread():
    ev = GithubRestNode.resolve_agent_event(_gh(
        ref="refs/heads/main", compare="https://github.example/acme-example/api/compare/a...b", pusher={"name": "dev-example"},
        commits=[{"id": "abcdef1234567", "message": "Fix login\n\nlong body", "author": {"name": "Dev Example"}}] * 12,
    ))
    assert_clean(ev)
    assert ev["text"].startswith("GitHub push by dev-example to main in acme-example/api (12 commit(s)):")
    assert "- abcdef1 Fix login (Dev Example)" in ev["text"] and "… and 2 more" in ev["text"]
    assert_names_real_operation(GithubRestNode, ev["text"], "get_commit")
    assert ev["conversation_key"] is None
    assert ev["title"] == "Push to main in acme-example/api"


def test_github_release_and_star():
    rel = GithubRestNode.resolve_agent_event(_gh(action="published", release={"name": "Spring", "tag_name": "v1.2.0", "body": "- login fix", "prerelease": True, "html_url": "https://github.example/r/v1.2.0"}))
    assert_clean(rel)
    assert "Release v1.2.0: Spring" in rel["text"] and "- prerelease: yes" in rel["text"]
    assert_names_real_operation(GithubRestNode, rel["text"], "get_release_by_tag")
    assert "tag=v1.2.0" in rel["text"] and rel["conversation_key"] is None
    star = GithubRestNode.resolve_agent_event(_gh(action="deleted", starred_at=None))
    assert_clean(star)
    assert star["text"].startswith("GitHub star deleted by octo-example on acme-example/api.")
    assert_names_real_operation(GithubRestNode, star["text"], "get_repository")


# ── GitLab ───────────────────────────────────────────────────────────────────

GL_PROJECT = {"id": 55, "name": "api", "path_with_namespace": "acme-example/api", "web_url": "https://gitlab.example/acme-example/api", "avatar_url": None, "namespace": "acme-example"}
GL_USER = {"name": "Dana Example", "username": "dana-example", "email": "dana@acme.example", "avatar_url": "https://avatars.example/9"}


def test_gitlab_issue_event_keys_on_iid_and_names_create_note():
    ev = GitLabNode.resolve_agent_event({
        "object_kind": "issue", "event_type": "issue", "user": GL_USER, "project": GL_PROJECT, "repository": {"name": "api"}, "_webhook": WEBHOOK,
        "object_attributes": {"iid": 12, "id": 900, "title": "Crash on start", "description": "Boot loop after upgrade.", "url": "https://gitlab.example/acme-example/api/-/issues/12", "state": "opened", "action": "open"},
        "labels": [{"id": 1, "title": "bug"}], "assignees": [{"name": "Sam Example"}],
    })
    assert_clean(ev, "avatar_url", "dana@acme.example")
    assert ev["text"].startswith("GitLab issue open by Dana Example in acme-example/api:")
    assert "Issue #12: Crash on start" in ev["text"] and "Boot loop after upgrade." in ev["text"]
    assert "- labels: bug" in ev["text"] and "- assignees: Sam Example" in ev["text"]
    assert "create_note with project_id=55, noteable_type=issues, noteable_iid=12" in ev["text"]
    assert_names_real_operation(GitLabNode, ev["text"], "create_note")
    assert ev["conversation_key"] == "acme-example/api#12"
    assert ev["title"] == "Issue #12: Crash on start"


def test_gitlab_note_on_merge_request_resumes_the_mr_thread():
    ev = GitLabNode.resolve_agent_event({
        "object_kind": "note", "user": GL_USER, "project": GL_PROJECT, "_webhook": WEBHOOK,
        "object_attributes": {"note": "Please rebase.", "noteable_type": "MergeRequest", "url": "https://gitlab.example/acme-example/api/-/merge_requests/7#note_1"},
        "merge_request": {"iid": 7, "title": "Fix auth", "source_branch": "fix/auth", "target_branch": "main"},
    })
    assert_clean(ev)
    assert ev["text"].startswith("GitLab comment by Dana Example on MR !7: Fix auth in acme-example/api:")
    assert "Please rebase." in ev["text"]
    assert "noteable_type=merge_requests, noteable_iid=7" in ev["text"]
    assert ev["conversation_key"] == "acme-example/api!7"
    assert ev["title"] == "MR !7: Fix auth"


def test_gitlab_push_and_pipeline():
    push = GitLabNode.resolve_agent_event({
        "object_kind": "push", "ref": "refs/heads/main", "user_name": "Dana Example", "project": GL_PROJECT, "_webhook": WEBHOOK,
        "commits": [{"id": "abcdef1234", "message": "Fix boot\n\nbody", "author": {"name": "Dana", "email": "dana@acme.example"}}],
    })
    assert_clean(push, "dana@acme.example")
    assert push["text"].startswith("GitLab push by Dana Example to main in acme-example/api (1 commit(s)):")
    assert "- abcdef12 Fix boot (Dana)" in push["text"]
    assert_names_real_operation(GitLabNode, push["text"], "get_project")
    assert push["conversation_key"] is None
    pipe = GitLabNode.resolve_agent_event({
        "object_kind": "pipeline", "user": GL_USER, "project": GL_PROJECT, "_webhook": WEBHOOK,
        "object_attributes": {"id": 900, "ref": "main", "status": "failed", "duration": 120},
    })
    assert_clean(pipe)
    assert pipe["text"].startswith("GitLab pipeline by Dana Example in acme-example/api:")
    assert '"status": "failed"' in pipe["text"]
    assert_names_real_operation(GitLabNode, pipe["text"], "get_pipeline")
    assert "pipeline_id=900" in pipe["text"]
    assert pipe["title"] == "Pipeline failed in acme-example/api"


# ── Linear ───────────────────────────────────────────────────────────────────

def _linear_issue(action="update", **extra):
    return {
        "type": "Issue", "action": action, "url": "https://linear.example/acme/issue/ACME-42", "actor": {"id": "u1", "name": "Dana Example"},
        "createdAt": "2026-09-12T10:00:00Z", "webhookId": "hook-uuid", "_webhook": WEBHOOK,
        "data": {
            "id": "iss-uuid-1", "identifier": "ACME-42", "title": "Login broken", "description": "500 on login.", "priority": 1, "priorityLabel": "Urgent",
            "state": {"id": "st-1", "name": "In Progress"}, "assignee": {"id": "u2", "name": "Sam Example"}, "team": {"id": "t1", "key": "ACME"}, "labels": [{"name": "bug"}],
        },
        **extra,
    }


def test_linear_issue_update_reads_type_and_action_from_the_top_level():
    ev = LinearNode.resolve_agent_event(_linear_issue(updatedFrom={"updatedAt": "2026-09-11T00:00:00Z", "stateId": "st-0"}))
    assert_clean(ev, "hook-uuid", "st-1")
    assert ev["text"].startswith("Linear issue updated by Dana Example in team ACME:")
    assert "ACME-42: Login broken" in ev["text"] and "500 on login." in ev["text"]
    assert "- state: In Progress" in ev["text"] and "- priority: Urgent" in ev["text"] and "- assignee: Sam Example" in ev["text"]
    assert "- changed stateId (was st-0)" in ev["text"] and "updatedAt" not in ev["text"]
    assert "create_issue_comment with issueId=iss-uuid-1" in ev["text"]
    assert_names_real_operation(LinearNode, ev["text"], "create_issue_comment", "get_issue")
    assert ev["conversation_key"] == "ACME-42"
    assert ev["title"] == "ACME-42: Login broken"


def test_linear_comment_keys_on_its_issue():
    ev = LinearNode.resolve_agent_event({
        "type": "Comment", "action": "create", "actor": {"name": "Dana Example"}, "_webhook": WEBHOOK,
        "data": {"id": "c1", "body": "Repro attached.", "url": "https://linear.example/c/1", "issue": {"id": "iss-uuid-1", "identifier": "ACME-42", "title": "Login broken"}, "user": {"name": "Dana Example"}},
    })
    assert_clean(ev)
    assert ev["text"].startswith("Linear comment created by Dana Example on ACME-42: Login broken:")
    assert "Repro attached." in ev["text"] and "issueId=iss-uuid-1" in ev["text"]
    assert ev["conversation_key"] == "ACME-42"
    assert ev["title"] == "Comment on ACME-42: Login broken"


def test_linear_project_has_no_thread():
    ev = LinearNode.resolve_agent_event({"type": "Project", "action": "create", "actor": {"name": "Dana Example"}, "data": {"id": "p1", "name": "Q4 Launch", "description": "Ship it.", "state": "started", "lead": {"name": "Sam Example"}, "url": "https://linear.example/p/1"}})
    assert_clean(ev)
    assert ev["text"].startswith("Linear project created by Dana Example:")
    assert "Q4 Launch" in ev["text"] and "- lead: Sam Example" in ev["text"]
    assert_names_real_operation(LinearNode, ev["text"], "get_project")
    assert ev["conversation_key"] is None and ev["title"] == "Project: Q4 Launch"


# ── Jira ─────────────────────────────────────────────────────────────────────

def _jira(**extra):
    return {
        "timestamp": 1757671200000, "webhookEvent": "jira:issue_updated", "issue_event_type_name": "issue_commented",
        "user": {"accountId": "acct-1", "displayName": "Dana Example", "avatarUrls": {"48x48": "https://avatars.example/1"}}, "_webhook": WEBHOOK,
        "issue": {
            "id": "10001", "key": "ACME-42", "self": "https://acme-example.atlassian.example/rest/api/2/issue/10001",
            "fields": {
                "summary": "Login broken",
                "description": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "500 on login."}]}]},
                "status": {"name": "To Do", "iconUrl": "https://icons.example/todo"}, "priority": {"name": "High"}, "issuetype": {"name": "Bug"},
                "project": {"key": "ACME", "name": "Acme"}, "assignee": {"displayName": "Sam Example"}, "reporter": {"displayName": "Dana Example"}, "labels": ["auth"],
            },
        },
        **extra,
    }


def test_jira_issue_commented_flattens_adf_and_keys_on_issue_key():
    ev = JiraNode.resolve_agent_event(_jira(
        changelog={"items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"}]},
        comment={"id": "c1", "body": "Looking now.", "author": {"displayName": "Sam Example"}},
    ))
    assert_clean(ev, "acct-1", "iconUrl", "avatarUrls")
    assert ev["text"].startswith("Jira issue commented by Dana Example in project ACME:")
    assert "ACME-42: Login broken" in ev["text"] and "500 on login." in ev["text"]
    assert "- status: To Do" in ev["text"] and "- labels: auth" in ev["text"]
    assert "- url: https://acme-example.atlassian.example/browse/ACME-42" in ev["text"]
    assert "- changed status: To Do → In Progress" in ev["text"]
    assert "Comment by Sam Example:\nLooking now." in ev["text"]
    assert "add_comment_to_issue with issue_key=ACME-42" in ev["text"]
    assert_names_real_operation(JiraNode, ev["text"], "add_comment_to_issue", "transition_issue_status", "get_issue")
    assert ev["conversation_key"] == "ACME-42"
    assert ev["title"] == "ACME-42: Login broken"


def test_jira_created_event_without_changelog_or_comment():
    payload = _jira(webhookEvent="jira:issue_created", issue_event_type_name="issue_created")
    payload["issue"]["fields"]["description"] = "plain string description"
    ev = JiraNode.resolve_agent_event(payload)
    assert_clean(ev)
    assert ev["text"].startswith("Jira issue created by Dana Example in project ACME:")
    assert "plain string description" in ev["text"] and "changed" not in ev["text"] and "Comment by" not in ev["text"]


# ── Notion (poll batches) ────────────────────────────────────────────────────

def _notion_page(pid, title):
    return {
        "object": "page", "id": pid, "url": f"https://notion.example/{pid}", "created_time": "2026-09-12T10:00:00Z", "last_edited_time": "2026-09-12T10:05:00Z",
        "parent": {"type": "database_id", "database_id": "db-1"}, "icon": None,
        "properties": {"Status": {"type": "select", "select": {"name": "Done"}}, "Name": {"type": "title", "title": [{"plain_text": title, "annotations": {"bold": False}}]}},
    }


def test_notion_page_batch_lists_titles_and_caps_at_ten():
    items = [_notion_page(f"p{i}", f"Page {i}") for i in range(12)]
    ev = NotionNode.resolve_agent_event({"items": items, "new_item_count": 12, "timing_ms": {"total": 3.2}})
    assert_clean(ev, "annotations", "db-1")
    assert ev["text"].startswith("Notion: 12 pages new or updated:")
    assert "- Page 0 (id p0) https://notion.example/p0" in ev["text"] and "- Page 9 (id p9)" in ev["text"]
    assert "- Page 10" not in ev["text"] and "… and 2 more" in ev["text"]
    assert_names_real_operation(NotionNode, ev["text"], "fetch_page_properties", "fetch_block_children", "query_notion_database")
    assert ev["conversation_key"] is None
    assert ev["title"] == "12 pages in Notion"


def test_notion_single_comment_and_empty_batch():
    ev = NotionNode.resolve_agent_event({"items": [{"object": "comment", "id": "c1", "parent": {"type": "page_id", "page_id": "p1"}, "discussion_id": "d1", "rich_text": [{"plain_text": "Can we "}, {"plain_text": "ship this?"}]}], "new_item_count": 1})
    assert_clean(ev)
    assert ev["text"].startswith("Notion: 1 comment created:")
    assert "- “Can we ship this?” on page p1" in ev["text"]
    assert_names_real_operation(NotionNode, ev["text"], "create_page_comment")
    assert ev["title"].startswith("Comment: “Can we ship this?”")
    assert NotionNode.resolve_agent_event({"items": [], "new_item_count": 0}) is None


def test_notion_single_page_title_names_the_page():
    ev = NotionNode.resolve_agent_event({"items": [_notion_page("p1", "Roadmap Q4")], "new_item_count": 1})
    assert ev["title"] == "Page: Roadmap Q4"
    assert "Notion: 1 page new or updated:" in ev["text"]


# ── Trello ───────────────────────────────────────────────────────────────────

def test_trello_card_move_names_lists_and_card_ops():
    ev = TrelloNode.resolve_agent_event({
        "model": {"id": "b1", "name": "Sprint", "url": "https://trello.example/b/b1"}, "_webhook": WEBHOOK,
        "action": {
            "id": "a1", "type": "updateCard", "date": "2026-09-12T10:00:00Z", "memberCreator": {"id": "m1", "fullName": "Dana Example", "username": "dana-example"},
            "data": {"card": {"id": "card1", "name": "Fix login", "shortLink": "abc", "idList": "l2"}, "board": {"id": "b1", "name": "Sprint"}, "listBefore": {"name": "Doing"}, "listAfter": {"name": "Done"}, "old": {"idList": "l1"}},
        },
    })
    assert_clean(ev, "m1")
    assert ev["text"].startswith("Trello update card by Dana Example on board “Sprint”:")
    assert "- card: Fix login" in ev["text"] and "- moved: Doing → Done" in ev["text"]
    assert "get_card or add_comment with card_id=card1" in ev["text"]
    assert_names_real_operation(TrelloNode, ev["text"], "get_card", "add_comment")
    assert ev["conversation_key"] is None
    assert ev["title"] == "Update card: Fix login"


def test_trello_comment_carries_the_text():
    ev = TrelloNode.resolve_agent_event({"action": {"type": "commentCard", "memberCreator": {"fullName": "Dana Example"}, "data": {"card": {"id": "card1", "name": "Fix login"}, "board": {"name": "Sprint"}, "text": "Blocked on infra."}}, "_webhook": WEBHOOK})
    assert_clean(ev)
    assert ev["text"].startswith("Trello comment card by Dana Example on board “Sprint”:")
    assert "- comment: Blocked on infra." in ev["text"]
    assert ev["title"] == "Comment card: Fix login"


# ── Asana ────────────────────────────────────────────────────────────────────

def test_asana_batch_says_ids_only_and_names_get_task():
    ev = AsanaNode.resolve_agent_event({"events": [
        {"action": "changed", "resource": {"gid": "1201", "resource_type": "task", "resource_subtype": "default_task"}, "parent": {"gid": "77", "resource_type": "project"}, "user": {"gid": "9"}, "change": {"field": "completed", "action": "changed"}, "created_at": "2026-09-12T10:00:00Z"},
        {"action": "added", "resource": {"gid": "1202", "resource_type": "task"}, "parent": {"gid": "77", "resource_type": "project"}, "user": {"gid": "9"}},
    ], "_webhook": WEBHOOK})
    assert_clean(ev)
    assert ev["text"].startswith("Asana: 2 event(s):")
    assert "- changed default_task 1201 in project 77 (changed completed) by user 9" in ev["text"]
    assert "- added task 1202 in project 77 by user 9" in ev["text"]
    assert "Asana sends ids, not content" in ev["text"] and "get_task with task_gid=1201" in ev["text"]
    assert_names_real_operation(AsanaNode, ev["text"], "get_task", "add_comment")
    assert ev["conversation_key"] is None
    assert ev["title"] == "2 Asana events"


def test_asana_single_event_title_and_empty_batch():
    ev = AsanaNode.resolve_agent_event({"events": [{"action": "added", "resource": {"gid": "1202", "resource_type": "task", "name": "Write docs"}, "parent": {"gid": "77", "resource_type": "project"}}]})
    assert ev["title"] == "Asana: added task 1202 “Write docs” in project 77"
    assert AsanaNode.resolve_agent_event({"events": []}) is None


# ── ClickUp ──────────────────────────────────────────────────────────────────

def test_clickup_status_update_renders_diff_and_names_get_task():
    ev = ClickUpNode.resolve_agent_event({
        "event": "taskStatusUpdated", "task_id": "abc123", "webhook_id": "wh-9", "_webhook": WEBHOOK,
        "history_items": [
            {"id": "h1", "field": "status", "before": {"status": "to do", "color": "#000"}, "after": {"status": "in progress", "color": "#fff"}, "user": {"id": 1, "username": "dana-example", "email": "dana@acme.example"}},
            {"id": "h2", "field": "assignee", "before": None, "after": {"username": "sam-example"}, "user": {"username": "dana-example"}},
        ],
    })
    assert_clean(ev, "wh-9", "dana@acme.example", "#fff")
    assert ev["text"].startswith("ClickUp task status updated on task abc123:")
    assert "- status: to do → in progress (by dana-example)" in ev["text"]
    assert "- assignee: — → sam-example (by dana-example)" in ev["text"]
    assert "title is not included" in ev["text"] and "get_task with task_id=abc123" in ev["text"]
    assert_names_real_operation(ClickUpNode, ev["text"], "get_task", "create_task_comment")
    assert ev["conversation_key"] is None
    assert ev["title"] == "Task status updated: task abc123"


def test_clickup_comment_posted_carries_the_text():
    ev = ClickUpNode.resolve_agent_event({"event": "taskCommentPosted", "task_id": "abc123", "history_items": [{"field": "comment", "comment": {"id": "c1", "text_content": "On it."}, "user": {"username": "sam-example"}}], "_webhook": WEBHOOK})
    assert_clean(ev)
    assert "- comment by sam-example: On it." in ev["text"]
    assert ev["title"] == "Task comment posted: task abc123"


# ── monday.com ───────────────────────────────────────────────────────────────

def test_monday_column_change_reads_labels_not_index_objects():
    ev = MondayNode.resolve_agent_event({"event": {
        "type": "change_column_value", "app": "monday", "boardId": 123, "pulseId": 456, "pulseName": "Fix login", "groupName": "This week",
        "columnId": "status", "columnType": "color", "columnTitle": "Status", "value": {"label": {"index": 1, "text": "Done", "style": {"color": "#00c875"}}},
        "previousValue": {"label": {"index": 0, "text": "Working on it"}}, "userId": 9, "triggerTime": "2026-09-12T10:00:00Z", "subscriptionId": 42,
    }, "_webhook": WEBHOOK})
    assert_clean(ev, "#00c875", "subscriptionId")
    assert ev["text"].startswith("monday.com change column value on board 123:")
    assert "- item: Fix login (id 456)" in ev["text"] and "- group: This week" in ev["text"]
    assert "- Status: Working on it → Done" in ev["text"]
    assert "get_items with item_ids=456" in ev["text"] and "create_update with item_id=456" in ev["text"]
    assert_names_real_operation(MondayNode, ev["text"], "get_items", "create_update")
    assert ev["conversation_key"] is None
    assert ev["title"] == "Fix login: Status changed"


def test_monday_update_event_carries_text_and_nameless_item_id():
    ev = MondayNode.resolve_agent_event({"event": {"type": "create_update", "boardId": 123, "pulseId": 456, "textBody": "Shipped to staging.", "userId": 9}, "_webhook": WEBHOOK})
    assert_clean(ev)
    assert "- item: id 456" in ev["text"] and "- update: Shipped to staging." in ev["text"]
    assert ev["title"] == "Create update"
