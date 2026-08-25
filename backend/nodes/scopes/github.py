"""GitHub operation → OAuth scope requirements.

GitHub's classic OAuth scopes are coarse: one scope covers a whole surface
rather than a single endpoint. ``repo`` in particular is enormous — "full access
to public and private repositories including read and write access to code,
commit statuses, repository invitations, collaborators, deployment statuses, and
repository webhooks" — which is why 210 of the node's 255 operations need
nothing else. Everything under ``/repos/**`` and the Actions/workflow-run
surface rides it (the Actions docs are explicit that workflow RUNS need ``repo``;
the separate ``workflow`` scope is only for adding/updating workflow FILES).

Three families sit outside it:

- **Public reads** (``/users/{u}``, ``/orgs/{o}``) need no scope at all.
- **Org / team reads** need ``read:org`` and **gists** need ``gist``. Neither
  was in ``x-oauth-scopes``, so those 25 operations could only fail; both are
  now declared here and therefore pulled into the connect request, which means
  existing credentials must be reconnected before those operations work.
- **Destructive admin** (``admin:org``, ``admin:org_hook``, ``delete_repo``)
  grants org-wide and repo-deletion power. Requesting those on the shared
  NoClick OAuth app would put "delete any of your repositories" and "fully
  manage the organization" on the consent screen for every user connecting
  GitHub, so they sit in the ``github_admin`` tier: excluded from the connect
  request, satisfiable only by a user-supplied Personal Access Token.

The connect-time request is DERIVED from this table
(``GITHUB_REQUESTED_SCOPES``) and consumed by ``GithubOAuthCredential``'s
``x-oauth-scopes`` and by ``nodes.oauth.github_oauth.GITHUB_WORKFLOW_SCOPES``,
so the requested list cannot drift from the operations that need it.
``user:email`` is the one scope no operation implies — the OAuth callback reads
the account's email — so it is declared as an ``extra_scopes`` entry.

Scope definitions verified against
https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps
plus the per-endpoint scope notes in the REST reference.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import DEFAULT_VARIANT, ScopeRegistry, ScopeRequirement

#: Scopes that cannot ride the shared OAuth app — see the module docstring.
GITHUB_ADMIN_TIER = "github_admin"


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


def _admin(scope: str, what: str) -> ScopeRequirement:
    return ScopeRequirement(
        scopes=(scope,),
        tier=GITHUB_ADMIN_TIER,
        credential_types=("github_pat",),
        note=(
            f"Needs the '{scope}' scope, which grants {what}. NoClick's shared "
            f"GitHub app deliberately does not request it. Connect a Personal "
            f"Access Token (classic) carrying '{scope}' instead."
        ),
    )


# `repo` — the catch-all for /repos/**, /user/repos, /user/starred, /search,
# /notifications (docs: "the notifications or repo scopes") and the Actions
# surface. Trigger operations register a repository webhook, which `repo`
# covers ("...and repository webhooks").
_REPO_OPS: tuple[str, ...] = (
    "add_labels_to_issue",
    "add_repo_collaborator",
    "approve_workflow_run",
    "cancel_workflow_run",
    "check_pull_request_merged",
    "check_user_is_collaborator",
    "compare_commits",
    "create_branch",
    "create_commit_comment",
    "create_commit_status",
    "create_deployment",
    "create_deployment_status",
    "create_issue",
    "create_issue_comment",
    "create_label",
    "create_milestone",
    "create_or_update_file",
    "create_org_repository",
    "create_pull_request",
    "create_pull_request_review",
    "create_pull_request_review_comment",
    "create_reaction_on_commit_comment",
    "create_reaction_on_issue",
    "create_reaction_on_issue_comment",
    "create_reaction_on_pr_review_comment",
    "create_reaction_on_release",
    "create_release",
    "create_repo_for_authenticated_user",
    "create_repo_from_template",
    "create_repo_webhook",
    "delete_artifact",
    "delete_branch",
    "delete_commit_comment_reaction",
    "delete_deployment",
    "delete_file",
    "delete_issue_comment",
    "delete_issue_comment_reaction",
    "delete_issue_reaction",
    "delete_label",
    "delete_milestone",
    "delete_pending_pull_request_review",
    "delete_pr_review_comment_reaction",
    "delete_pull_request_review_comment",
    "delete_release",
    "delete_release_asset",
    "delete_release_reaction",
    "delete_repo_webhook",
    "delete_workflow_run",
    "delete_workflow_run_logs",
    "dismiss_pull_request_review",
    "download_artifact",
    "download_workflow_run_attempt_logs",
    "download_workflow_run_logs",
    "fork_repository",
    "generate_release_notes",
    "get_artifact",
    "get_commit",
    "get_deployment",
    "get_deployment_status",
    "get_file_contents",
    "get_issue",
    "get_issue_comment",
    "get_label",
    "get_latest_release",
    "get_milestone",
    "get_pull_request",
    "get_pull_request_review_comment",
    "get_release",
    "get_release_asset",
    "get_release_by_tag",
    "get_repo_languages",
    "get_repo_topics",
    "get_repo_webhook",
    "get_repository",
    "get_user_repo_permissions",
    "get_webhook_delivery",
    "get_workflow_run",
    "get_workflow_run_attempt",
    "get_workflow_run_usage",
    "list_authenticated_user_repos",
    "list_branches",
    "list_branches_by_head_commit",
    "list_commit_check_runs",
    "list_commit_comment_reactions",
    "list_commit_comments",
    "list_commits",
    "list_deployment_statuses",
    "list_deployments",
    "list_issue_assignees",
    "list_issue_comment_reactions",
    "list_issue_comments",
    "list_issue_reactions",
    "list_issues",
    "list_milestones",
    "list_notifications",
    "list_org_repos",
    "list_org_repos_alias",
    "list_pr_review_comment_reactions",
    "list_pull_request_commits",
    "list_pull_request_files",
    "list_pull_request_review_comments",
    "list_pull_request_reviews",
    "list_pull_requests",
    "list_pull_requests_by_commit",
    "list_release_assets",
    "list_release_reactions",
    "list_releases",
    "list_repo_artifacts",
    "list_repo_collaborators",
    "list_repo_contributors",
    "list_repo_directory_contents",
    "list_repo_forks",
    "list_repo_invitations",
    "list_repo_labels",
    "list_repo_stargazers",
    "list_repo_tags",
    "list_review_comments_for_review",
    "list_webhook_deliveries",
    "list_workflow_run_artifacts",
    "list_workflow_run_attempt_jobs",
    "list_workflow_run_jobs",
    "list_workflow_run_pending_deployments",
    "list_workflow_runs",
    "list_workflows",
    "lock_issue",
    "mark_notifications_as_read",
    "merge_pull_request",
    "ping_repo_webhook",
    "redeliver_webhook",
    "remove_all_labels_from_issue",
    "remove_label_from_issue",
    "remove_repo_collaborator",
    "reply_to_pull_request_review_comment",
    "request_pull_request_reviewers",
    "rerun_workflow",
    "search_code",
    "search_issues",
    "search_repositories",
    "set_issue_labels",
    "set_repo_topics",
    "star_repository",
    "submit_pull_request_review",
    "test_repo_webhook",
    "transfer_repository",
    "trigger_workflow_dispatch",
    "unlock_issue",
    "unstar_repository",
    "update_issue",
    "update_issue_comment",
    "update_label",
    "update_milestone",
    # "OAuth app tokens ... need the admin:org or repo scope to use this
    # endpoint" — repo satisfies it, so no admin scope is needed here.
    "update_organization",
    "update_pull_request",
    "update_pull_request_branch",
    "update_pull_request_review",
    "update_pull_request_review_comment",
    "update_release",
    "update_release_asset",
    "update_repo_invitation",
    "update_repo_webhook",
    "update_repository",
)

# Push triggers. Each registers a repository webhook (POST /repos/{o}/{r}/hooks)
# and receives deliveries; `repo` covers repository webhooks outright, so no
# admin:repo_hook is needed.
_TRIGGER_OPS: tuple[str, ...] = (
    "on_issue_assigned",
    "on_issue_closed",
    "on_issue_comment",
    "on_issue_deleted",
    "on_issue_demilestoned",
    "on_issue_edited",
    "on_issue_labeled",
    "on_issue_locked",
    "on_issue_milestoned",
    "on_issue_opened",
    "on_issue_pinned",
    "on_issue_reopened",
    "on_issue_transferred",
    "on_issue_unassigned",
    "on_issue_unlabeled",
    "on_issue_unlocked",
    "on_issue_unpinned",
    "on_pull_request_assigned",
    "on_pull_request_auto_merge_disabled",
    "on_pull_request_auto_merge_enabled",
    "on_pull_request_closed",
    "on_pull_request_converted_to_draft",
    "on_pull_request_demilestoned",
    "on_pull_request_dequeued",
    "on_pull_request_edited",
    "on_pull_request_enqueued",
    "on_pull_request_labeled",
    "on_pull_request_locked",
    "on_pull_request_merged",
    "on_pull_request_milestoned",
    "on_pull_request_opened",
    "on_pull_request_ready_for_review",
    "on_pull_request_reopened",
    "on_pull_request_review_request_removed",
    "on_pull_request_review_requested",
    "on_pull_request_synchronize",
    "on_pull_request_unassigned",
    "on_pull_request_unlabeled",
    "on_pull_request_unlocked",
    "on_push",
    "on_release_created",
    "on_release_deleted",
    "on_release_edited",
    "on_release_prereleased",
    "on_release_published",
    "on_release_released",
    "on_release_unpublished",
    "on_star_created",
    "on_star_deleted",
)

# Endpoints GitHub serves without authentication. `get_organization` returns the
# public org fields; admin:org is only needed for the owner-only detail set.
_PUBLIC_OPS: tuple[str, ...] = (
    "get_organization",
    "get_user",
    "list_user_followers",
    "list_user_following",
    "list_user_repos",
)

# `read:org` — "Read-only access to organization membership, organization
# projects, and team membership." Team endpoints (/orgs/{o}/teams/**) and the
# org/team membership reads all sit behind it; none of them are covered by
# `repo`, and none need the write-capable `admin:org`.
_ORG_READ_OPS: tuple[str, ...] = (
    "check_org_membership",
    "check_team_repo_permissions",
    "get_org_membership",
    "get_team",
    "get_team_membership",
    "list_org_members",
    "list_org_members_alias",
    "list_org_teams",
    "list_team_members",
    "list_team_repos",
)

# `gist` — "To read or write gists on a user's behalf, you need the gist OAuth
# scope and a token." GitHub documents the scope for the surface as a whole and
# does not qualify it per endpoint, so the public-gist reads declare it too.
_GIST_OPS: tuple[str, ...] = (
    "check_gist_starred",
    "create_gist",
    "delete_gist",
    "fork_gist",
    "get_gist",
    "get_gist_revision",
    "list_authenticated_user_gists",
    "list_gist_commits",
    "list_gist_forks",
    "list_public_gists",
    "list_starred_gists",
    "list_user_gists",
    "star_gist",
    "unstar_gist",
    "update_gist",
)

# Destructive, org-wide, or repo-deleting. Excluded from the connect request.
# scope -> (what it grants, operations)
_ADMIN_OPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "admin:org": (
        "full management of the organization, its teams and its memberships",
        (
            "add_or_update_org_membership",
            "add_or_update_team_repo_permissions",
            "cancel_org_invitation",
            "create_team",
            "delete_team",
            "list_org_invitations",
            "list_pending_org_invitations",
            "remove_org_member",
            "remove_org_membership",
            "remove_repo_from_team",
            "update_team",
        ),
    ),
    "admin:org_hook": (
        "read, write, ping and delete access to organization hooks",
        ("create_org_webhook", "list_org_webhooks"),
    ),
    "delete_repo": (
        "the ability to delete any repository you administer",
        ("delete_repository",),
    ),
}


_REQUIREMENTS: dict[str, ScopeRequirement] = {}
for _op in _REPO_OPS + _TRIGGER_OPS:
    _REQUIREMENTS[_op] = _s("repo")
for _op in _PUBLIC_OPS:
    _REQUIREMENTS[_op] = _s()
for _op in _ORG_READ_OPS:
    _REQUIREMENTS[_op] = _s("read:org")
for _op in _GIST_OPS:
    _REQUIREMENTS[_op] = _s("gist")
_REQUIREMENTS["get_authenticated_user"] = _s("read:user")
for _scope, (_what, _admin_ops) in _ADMIN_OPS.items():
    for _op in _admin_ops:
        _REQUIREMENTS[_op] = _admin(_scope, _what)


GITHUB_SCOPES = ScopeRegistry(
    provider="github",
    requirements=_REQUIREMENTS,
    # Read of the account's email addresses at callback time; no operation
    # calls /user/emails, so no endpoint implies it.
    extra_scopes={DEFAULT_VARIANT: ("user:email",)},
)

#: Scopes requested at connect time, derived from the table above.
GITHUB_REQUESTED_SCOPES: list[str] = GITHUB_SCOPES.declared_scopes()
