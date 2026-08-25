"""Linear operation → OAuth scope requirements.

Linear grants scopes per capability, not per GraphQL field. The documented set
(https://linear.app/developers/oauth-2-0-authentication) is:

``read``
    "(Default) Read access for the user's account. This scope will always be
    present."
``write``
    "Write access for the user's account. If your application only needs to
    create comments, use a more targeted scope"
``issues:create`` / ``comments:create``
    Narrower alternatives to ``write`` — "Allows creating new issues and their
    attachments" / "Allows creating new issue comments". The node requests both
    alongside ``write``; a token holding ``write`` already covers those
    mutations, so they are not declared per-operation.
``admin``
    "Full access to admin level endpoints. You should never ask for this
    permission unless it's absolutely needed."

The one place Linear documents a scope against specific operations is webhooks
(https://linear.app/developers/webhooks): "Only workspace admins, or OAuth
applications with the ``admin`` scope, can create or read webhooks." That covers
``webhookCreate`` and the ``webhooks`` query verbatim, and ``webhookDelete`` via
"Creating and managing webhooks requires admin permissions"
(https://linear.app/docs/api-and-webhooks). Every trigger operation registers
its subscription with ``webhookCreate``, so the triggers need ``admin`` too.

Everything else is split on the documented read/write meaning of the scopes
themselves — Linear publishes no per-field scope table, so queries take ``read``
and mutations take ``write``. Nothing here needs a scope the node does not
already request.

Two documented caveats worth knowing, neither of which changes the table:

- ``customer:*`` and ``initiative:*`` are separately gated, so plain
  ``read``/``write`` do NOT blanket the whole API. The node exposes no customer
  or initiative operation today; adding one needs a new scope.
- "integrations using the ``actor=app`` mode are not able to also request
  ``admin`` scope" (https://linear.app/developers/agents), so an app-actor
  credential can never run the webhook or trigger operations.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_READ_OPS: tuple[str, ...] = (
    "get_authenticated_user",
    "get_document",
    "get_issue",
    "get_project",
    "get_team",
    "get_user",
    "list_documents",
    "list_issue_attachments",
    "list_issue_comments",
    "list_issue_labels",
    "list_issue_relations",
    "list_issues",
    "list_project_milestones",
    "list_projects",
    "list_team_cycles",
    "list_team_workflow_states",
    "list_teams",
    "list_users",
    "search_issues",
)

_WRITE_OPS: tuple[str, ...] = (
    "archive_cycle",
    "archive_issue",
    "archive_project",
    "create_cycle",
    "create_document",
    "create_issue",
    "create_issue_attachment",
    "create_issue_comment",
    "create_issue_label",
    "create_issue_relation",
    "create_project",
    "create_project_milestone",
    "delete_attachment",
    "delete_document",
    "delete_issue",
    "delete_issue_comment",
    "delete_issue_label",
    "delete_issue_relation",
    "delete_project",
    "delete_project_milestone",
    "unarchive_issue",
    "update_cycle",
    "update_document",
    "update_issue",
    "update_issue_comment",
    "update_issue_label",
    "update_project",
    "update_project_milestone",
)

# webhookCreate / webhookDelete / the webhooks query. The triggers are here
# because each registers its subscription through webhookCreate.
_ADMIN_OPS: tuple[str, ...] = (
    "create_webhook",
    "delete_webhook",
    "list_webhooks",
    "on_comment_created",
    "on_comment_deleted",
    "on_comment_updated",
    "on_issue_created",
    "on_issue_deleted",
    "on_issue_updated",
    "on_project_created",
    "on_project_deleted",
    "on_project_updated",
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {}
for _op in _READ_OPS:
    _REQUIREMENTS[_op] = _s("read")
for _op in _WRITE_OPS:
    _REQUIREMENTS[_op] = _s("write")
for _op in _ADMIN_OPS:
    _REQUIREMENTS[_op] = _s("admin")


LINEAR_SCOPES = ScopeRegistry(
    provider="linear",
    requirements=_REQUIREMENTS,
)
