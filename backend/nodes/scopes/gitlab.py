"""GitLab operation → OAuth scope requirements.

GitLab's OAuth scopes are resource-coarse rather than endpoint-fine. The two the
node requests are, verbatim from
https://docs.gitlab.com/integration/oauth_provider/:

``api``
    "Grants complete read/write access to the API, including all groups and
    projects, the container registry, the dependency proxy, and the package
    registry."
``read_user``
    "Grants read-only access to the authenticated user's profile through the
    ``/user`` API endpoint, which includes username, public email, and full
    name."

Every operation in this node is a REST call under ``/api/v4``, so ``api``
covers the whole surface — including webhook registration for the two trigger
operations, which is an ordinary API call on GitLab (no separate hook scope
exists). The narrower ``read_api`` would suffice for the reads, and
``read_repository``/``write_repository`` exist but are Git-over-HTTPS scopes
("not using the API"), so no operation here needs them.

Nothing is missing: there is no GitLab endpoint in this node that ``api`` does
not authorize. Failures on the admin-flavored operations (``add_member``,
``protect_branch``, group hooks) come from the user's PROJECT ROLE, not from a
scope — GitLab has no scope that can grant a Reporter Maintainer powers.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _api() -> ScopeRequirement:
    return ScopeRequirement(scopes=("api",))


# `api` grants complete read/write API access, so it is the requirement for
# every REST operation the node exposes — reads included, since `read_api` is
# not among the requested scopes and `api` subsumes it.
_API_OPS: tuple[str, ...] = (
    "add_member",
    "approve_merge_request",
    "cancel_job",
    "cancel_pipeline",
    "create_branch",
    "create_commit",
    "create_deployment",
    "create_environment",
    "create_epic",
    "create_hook",
    "create_issue",
    "create_label",
    "create_merge_request",
    "create_milestone",
    "create_note",
    "create_pipeline",
    "create_project",
    "create_release",
    "create_tag",
    "create_variable",
    "create_wiki",
    "delete_branch",
    "delete_environment",
    "delete_hook",
    "delete_issue",
    "delete_label",
    "delete_release",
    "delete_variable",
    "delete_wiki",
    "get_deployment",
    "get_file",
    "get_issue",
    "get_job",
    "get_job_log",
    "get_merge_request",
    "get_pipeline",
    "get_project",
    "get_release",
    "get_wiki",
    "list_branches",
    "list_commits",
    "list_deployments",
    "list_environments",
    "list_epics",
    "list_groups",
    "list_hooks",
    "list_issues",
    "list_labels",
    "list_members",
    "list_merge_requests",
    "list_milestones",
    "list_notes",
    "list_pipeline_jobs",
    "list_pipelines",
    "list_projects",
    "list_protected_branches",
    "list_releases",
    "list_todos",
    "list_variables",
    "list_wikis",
    "mark_all_todos_done",
    "mark_todo_done",
    "merge_merge_request",
    "play_job",
    "protect_branch",
    "remove_member",
    "retry_job",
    "retry_pipeline",
    "search",
    "set_commit_status",
    "stop_environment",
    "unapprove_merge_request",
    "unprotect_branch",
    "update_epic",
    "update_issue",
    "update_merge_request",
    "update_release",
    "update_variable",
    "update_wiki",
    "upsert_file",
    # Triggers: both register a project/group hook through the REST API, which
    # `api` authorizes. Group hooks additionally need a Premium plan — a
    # licensing limit, not a scope one.
    "on_group_event",
    "on_project_event",
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {op: _api() for op in _API_OPS}

# GET /user — the one endpoint `read_user` exists for.
_REQUIREMENTS["get_user"] = ScopeRequirement(scopes=("read_user",))


GITLAB_SCOPES = ScopeRegistry(
    provider="gitlab",
    requirements=_REQUIREMENTS,
)
