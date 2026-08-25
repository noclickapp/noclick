"""Pipedrive operation → OAuth scope requirements.

Mapped from Pipedrive's published scope/endpoint table
(https://pipedrive.readme.io/docs/marketplace-scopes-and-permissions-explanations),
which lists every endpoint path each marketplace scope grants. The node's
``OP_SPECS`` carries the exact method + path per operation, so each entry here is
a direct lookup of that path in the published table rather than a guess.

Three quirks shape the table:

- **``<entity>:full`` subsumes ``<entity>:read``.** Pipedrive's table repeats
  every ``:read`` GET under the matching ``:full`` scope. This node requests only
  the ``:full`` variants, so read operations are declared against ``:full`` — the
  scope the credential actually carries. A minimal app could satisfy them with
  ``deals:read`` / ``contacts:read`` / etc.; the registry has no notion of scope
  implication, so declaring the narrower string would read as a missing scope.
- **Scopes are grouped by workflow, not by URL prefix.** Notes, files and filters
  live under ``deals:full`` / ``contacts:full`` / ``activities:full`` rather than
  a scope of their own, and pipelines/stages READS ride ``deals:read`` while
  their WRITES are ``admin``-only.
- **Custom-field writes need a dedicated scope.** ``deal-fields:full``,
  ``contact-fields:full`` and ``project-fields:full`` gate POST/PUT/PATCH/DELETE
  on ``/dealFields``, ``/personFields`` and ``/organizationFields``. Product
  field writes are the exception — Pipedrive folds them into ``products:full``.

Trigger operations register a Pipedrive webhook (``POST /webhooks``) and then
receive object payloads, so they require ``webhooks:full`` plus read access to
the object they subscribe to — a webhook only delivers objects the app's scopes
cover.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


# op names grouped by the scope set they need, keyed by that set.
_BY_SCOPES: dict[tuple[str, ...], tuple[str, ...]] = {
    # -- base: account-level reads available to every install ---------------
    ("base",): (
        "get_current_user",  # GET /users/me
        "get_user_settings",  # GET /userSettings
        "list_user_connections",  # GET /userConnections
        "list_currencies",  # GET /currencies
    ),
    # -- users:read ---------------------------------------------------------
    # Legacy-team READS sit under users:read; their writes are admin-only.
    ("users:read",): (
        "find_users",
        "get_user",
        "list_users",
        "list_user_followers",
        "list_user_permissions",
        "list_user_role_assignments",
        "list_user_role_settings",
        "get_legacy_team",
        "list_legacy_teams",
        "list_legacy_team_users",
        "list_user_legacy_teams",
    ),
    # -- search:read / recents:read -----------------------------------------
    ("search:read",): (
        "item_search",
        "item_search_by_field",
    ),
    # /recents plus the per-object flow and changelog feeds.
    ("recents:read",): (
        "list_recents",
        "get_deal_changelog",
        "get_deal_flow",
        "list_person_changelog",
        "list_person_updates",
        "list_organization_changelog",
        "list_organization_updates",
    ),
    ("webhooks:full",): (
        "create_webhook",
        "delete_webhook",
        "list_webhooks",
    ),
    # -- deals:full ---------------------------------------------------------
    # Also carries notes, files, filters, and pipeline/stage READS.
    ("deals:full",): (
        # deals
        "create_deal",
        "get_deal",
        "update_deal",
        "delete_deal",
        "list_deals",
        "search_deals",
        "duplicate_deal",
        "merge_deals",
        "convert_deal_to_lead",
        "get_deal_conversion_status",
        "list_archived_deals",
        "get_archived_deals_summary",
        "get_archived_deals_timeline",
        "get_deals_summary",
        "get_deals_timeline",
        "get_deals_products_across",
        "list_deal_permitted_users",
        # deal field READS (writes need deal-fields:full — see unmapped)
        "get_deal_field",
        "get_deal_field_v2",
        "get_deal_fields",
        "get_deal_fields_v2",
        # deal sub-resources
        "add_deal_discount",
        "update_deal_discount",
        "delete_deal_discount",
        "list_deal_discounts",
        "add_deal_installment",
        "update_deal_installment",
        "delete_deal_installment",
        "list_deals_installments",
        "add_deal_follower",
        "add_deal_follower_v1",
        "delete_deal_follower",
        "delete_deal_follower_v1",
        "list_deal_followers",
        "list_deal_followers_v1",
        "list_deal_followers_changelog",
        "add_deal_participant",
        "delete_deal_participant",
        "list_deal_participants",
        "list_deal_participants_changelog",
        "add_deal_product",
        "add_deal_products_bulk",
        "update_deal_product",
        "delete_deal_product",
        "delete_many_deal_products",
        "list_deal_products",
        "list_deal_files",
        # deals of a related object
        "list_organization_deals",
        "list_person_deals",
        "get_product_deals",
        # files
        "add_file_remote",
        "link_file_remote",
        "get_file",
        "list_files",
        "update_file",
        "delete_file",
        "download_file",
        # filters
        "add_filter",
        "get_filter",
        "get_filter_helpers",
        "list_filters",
        "update_filter",
        "delete_filter",
        "delete_filters_bulk",
        # notes
        "create_note",
        "get_note",
        "list_notes",
        "update_note",
        "delete_note",
        "get_note_fields",
        "add_note_comment",
        "get_note_comment",
        "list_note_comments",
        "update_note_comment",
        "delete_note_comment",
        # pipelines / stages — READS only; writes are admin (see unmapped)
        "get_pipeline",
        "list_pipelines",
        "get_pipeline_deals",
        "get_pipeline_conversion_statistics",
        "get_pipeline_movement_statistics",
        "get_stage",
        "list_stages",
        "get_stage_deals",
    ),
    # -- contacts:full (persons + organizations) ----------------------------
    ("contacts:full",): (
        "create_person",
        "get_person",
        "list_persons",
        "search_persons",
        "update_person",
        "delete_person",
        "delete_persons_bulk",
        "merge_person",
        "get_person_picture",
        "delete_person_picture",
        "add_person_follower",
        "delete_person_follower",
        "list_person_followers",
        "list_person_followers_changelog",
        "list_person_permitted_users",
        "list_person_files",
        "list_person_products",
        "get_person_field",
        "list_person_fields",
        "create_organization",
        "get_organization",
        "list_organizations",
        "search_organizations",
        "update_organization",
        "delete_organization",
        "delete_organizations_bulk",
        "merge_organization",
        "add_organization_follower",
        "delete_organization_follower",
        "list_organization_followers",
        "list_organization_followers_changelog",
        "list_organization_permitted_users",
        "list_organization_files",
        "list_organization_persons",
        "get_organization_field",
        "list_organization_fields",
        "create_organization_relationship",
        "get_organization_relationship",
        "list_organization_relationships",
        "update_organization_relationship",
        "delete_organization_relationship",
    ),
    # -- activities:full ----------------------------------------------------
    ("activities:full",): (
        "create_activity",
        "get_activity",
        "list_activities",
        "update_activity",
        "delete_activity",
        "get_activity_fields",
        "list_activity_types",  # READ only; type writes are admin
        "list_person_activities",
        "list_organization_activities",
    ),
    # -- leads:full ---------------------------------------------------------
    ("leads:full",): (
        "create_lead",
        "get_lead",
        "list_leads",
        "search_leads",
        "update_lead",
        "delete_lead",
        "get_lead_permitted_users",
        "list_lead_sources",
        "add_lead_label",
        "list_lead_labels",
        "update_lead_label",
        "delete_lead_label",
    ),
    # -- products:full ------------------------------------------------------
    # Product FIELD writes are folded into products:full — unlike deal/person
    # fields, which need their own *-fields:full scope.
    ("products:full",): (
        "create_product",
        "get_product",
        "list_products",
        "search_products",
        "update_product",
        "delete_product",
        "duplicate_product",
        "get_product_files",
        "get_product_permitted_users",
        "add_product_follower",
        "delete_product_follower",
        "list_product_followers",
        "get_product_followers_changelog",
        "list_product_images",
        "delete_product_image",
        "create_product_variation",
        "list_product_variations",
        "update_product_variation",
        "delete_product_variation",
        "create_product_field",
        "get_product_field",
        "list_product_fields",
        "update_product_field",
        "delete_product_field",
        "delete_product_fields",
        "add_product_field_options",
        "update_product_field_options",
        "delete_product_field_options",
    ),
    # -- triggers: register a webhook, then receive that object's payload ----
    ("webhooks:full", "deals:full"): (
        "on_deal_created",
        "on_deal_changed",
        "on_deal_deleted",
        # notes, pipelines and stages are all readable under deals:read.
        "on_note_created",
        "on_note_changed",
        "on_note_deleted",
        "on_pipeline_created",
        "on_pipeline_changed",
        "on_pipeline_deleted",
        "on_stage_created",
        "on_stage_changed",
        "on_stage_deleted",
    ),
    ("webhooks:full", "contacts:full"): (
        "on_person_created",
        "on_person_changed",
        "on_person_deleted",
        "on_organization_created",
        "on_organization_changed",
        "on_organization_deleted",
    ),
    ("webhooks:full", "activities:full"): (
        "on_activity_created",
        "on_activity_changed",
        "on_activity_deleted",
    ),
    ("webhooks:full", "leads:full"): (
        "on_lead_created",
        "on_lead_changed",
        "on_lead_deleted",
    ),
    ("webhooks:full", "products:full"): (
        "on_product_created",
        "on_product_changed",
        "on_product_deleted",
    ),
    ("webhooks:full", "users:read"): (
        "on_user_created",
        "on_user_changed",
        "on_user_deleted",
    ),
}

# Subscribes to `*`/`*`, so the objects it can actually deliver are whatever the
# credential's other scopes cover. Only the webhook itself is a fixed need.
_ANY_EVENT_NOTE = (
    "Delivers only the object types your Pipedrive scopes already grant read "
    "access to."
)

_REQUIREMENTS: dict[str, ScopeRequirement] = {
    operation: _s(*scopes)
    for scopes, operations in _BY_SCOPES.items()
    for operation in operations
}
_REQUIREMENTS["on_pipedrive_any_event"] = ScopeRequirement(
    scopes=("webhooks:full",), note=_ANY_EVENT_NOTE
)


PIPEDRIVE_SCOPES = ScopeRegistry(
    provider="pipedrive",
    requirements=_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: admin — pipeline/stage/user/activity-type writes and
        # the whole roles + permission-sets + legacy-team-write surface are
        # `admin`-only. The node never requests it, so all of these return 403.
        "add_activity_type",
        "update_activity_type",
        "delete_activity_type",
        "create_pipeline",
        "update_pipeline",
        "delete_pipeline",
        "create_stage",
        "update_stage",
        "delete_stage",
        "create_user",
        "update_user",
        "create_legacy_team",
        "update_legacy_team",
        "add_legacy_team_users",
        "delete_legacy_team_users",
        "create_role",
        "get_role",
        "list_roles",
        "update_role",
        "delete_role",
        "add_role_assignment",
        "list_role_assignments",
        "delete_role_assignment",
        "add_role_setting",
        "get_role_settings",
        "list_role_pipelines",
        "update_role_pipelines",
        "get_permission_set",
        "list_permission_sets",
        "list_permission_set_assignments",
        # MISSING SCOPE: deal-fields:full (or admin) — reading deal fields
        # rides deals:read, but creating/updating/deleting them does not.
        "add_deal_field",
        "add_deal_field_v2",
        "update_deal_field",
        "update_deal_field_v2",
        "delete_deal_field",
        "delete_deal_field_v2",
        "delete_deal_fields",
        "add_deal_field_options_v2",
        "update_deal_field_options_v2",
        "delete_deal_field_options_v2",
        # MISSING SCOPE: contact-fields:full (or admin) — same split for
        # person and organization custom fields.
        "create_person_field",
        "update_person_field",
        "delete_person_field",
        "delete_person_fields_bulk",
        "create_organization_field",
        "update_organization_field",
        "delete_organization_field",
        "delete_organization_fields_bulk",
        # MISSING SCOPE: mail:read — every mailbox read, including the
        # per-object mailMessages feeds.
        "get_mail_message",
        "get_mail_thread",
        "list_mail_threads",
        "list_mail_thread_messages",
        "list_deal_mail_messages",
        "list_person_mail_messages",
        "list_organization_mail_messages",
        # MISSING SCOPE: mail:full — mail thread mutation.
        "update_mail_thread",
        "delete_mail_thread",
        # MISSING SCOPE: goals:read — goal reads.
        "find_goals",
        "get_goal_results",
        # MISSING SCOPE: goals:full — goal writes.
        "add_goal",
        "update_goal",
        "delete_goal",
        # MISSING SCOPE: projects:read — the entire projects/tasks read surface.
        "get_project",
        "list_projects",
        "get_project_activities",
        "get_project_board",
        "get_project_groups",
        "get_project_phase",
        "get_project_plan",
        "get_project_template",
        "list_project_templates",
        "get_task",
        "list_tasks",
        # MISSING SCOPE: projects:full — projects/tasks writes.
        "add_project",
        "update_project",
        "delete_project",
        "archive_project",
        "update_project_plan_activity",
        "update_project_plan_task",
        "add_task",
        "update_task",
        "delete_task",
        # MISSING SCOPE: phone-integration — the /callLogs surface.
        "add_call_log",
        "add_call_log_recording",
        "get_call_log",
        "list_call_logs",
        "delete_call_log",
        # MISSING SCOPE: messengers-integration — the /channels surface.
        "add_channel",
        "delete_channel",
        "delete_channel_conversation",
        "receive_channel_message",
        # MISSING SCOPE: video-calls — meeting provider links.
        "add_user_provider_link",
        "delete_user_provider_link",
    ),
)
