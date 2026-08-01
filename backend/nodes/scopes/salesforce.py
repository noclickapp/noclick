"""Salesforce operation → OAuth scope requirements.

Salesforce's scopes are coarse: they gate whole API *families*, not objects or
verbs, so this registry is deliberately flat and small. There is no per-object
granularity to express — record-level access is governed by the logged-in user's
profile and sharing rules, not by the OAuth grant. Do not read the uniformity
here as an unfinished table.

Three scopes matter for this node
(https://developer.salesforce.com/docs/platform/mobile-sdk/guide/oauth-scope-parameter-values.html):

``api``
    "Allows access to the current, logged-in user's account using APIs, such as
    REST API and Bulk API 2.0." Covers all but three of this node's operations —
    records, SOQL/SOSL, composite, metadata/layouts, list views, quick actions,
    invocable actions, approvals, bulk jobs, files, and the Reports & Dashboards
    REST API (``/services/data/vXX/analytics/...``, a standard REST resource, not
    the separate CRM Analytics ``wave_api`` surface).
``full``
    "Allows access to all data accessible by the logged-in user, and encompasses
    all other scopes." The two Chatter operations call Connect REST API
    (``/services/data/vXX/chatter/...``), whose own scope is ``chatter_api``, and
    ``get_current_user_info`` calls the identity URL (``/services/oauth2/userinfo``),
    whose own scope is ``id``. Neither narrower scope is requested, and neither is
    missing: ``full`` subsumes both. They are declared against ``full`` — the
    scope the credential actually carries — with the narrower alternative in the
    requirement's note.
``refresh_token``
    Grants nothing; it only makes the token endpoint return a refresh token. No
    operation implies it, so it is declared as an extra scope.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: REST API + Bulk API 2.0 — everything this node does except Chatter/identity.
_API = ScopeRequirement(scopes=("api",))

#: Connect REST API. Narrower alternative: `chatter_api`.
_CHATTER = ScopeRequirement(
    scopes=("full",),
    note="Chatter uses Connect REST API, which needs `chatter_api` or `full`.",
)

#: Identity URL service. Narrower alternative: `id` / `openid`.
_IDENTITY = ScopeRequirement(
    scopes=("full",),
    note="The identity URL needs `id` (or `openid`) or `full`.",
)


_API_OPERATIONS: tuple[str, ...] = (
    # -- SOQL / SOSL ------------------------------------------------------
    "execute_soql_query",
    "execute_soql_query_including_deleted",
    "get_query_result_next_batch",
    "execute_sosl_search",
    # -- records ----------------------------------------------------------
    "create_single_record",
    "get_single_record",
    "update_single_record",
    "delete_single_record",
    "create_multiple_records",
    "update_multiple_records",
    "delete_multiple_records",
    "create_nested_record_tree",
    "upsert_record_by_external_id",
    "get_deleted_records_in_range",
    "get_updated_records_in_range",
    "get_recently_viewed_records",
    # -- describe / metadata ----------------------------------------------
    "list_available_sobjects",
    "get_sobject_metadata",
    "get_org_global_metadata",
    "get_sobject_compact_layouts",
    "get_sobject_page_layouts",
    "get_available_api_versions",
    "get_org_api_limits",
    "get_user_available_tabs",
    # -- composite ---------------------------------------------------------
    "execute_composite_api_request",
    # -- list views --------------------------------------------------------
    "list_object_list_views",
    "get_list_view_details",
    "execute_list_view_query",
    # -- quick / invocable actions ----------------------------------------
    "list_global_quick_actions",
    "list_object_quick_actions",
    "execute_quick_action",
    "list_invocable_actions",
    "get_invocable_action_details",
    "execute_invocable_action",
    # -- approvals ---------------------------------------------------------
    "list_approval_processes",
    "submit_record_for_approval",
    "approve_or_reject_approval_request",
    # -- reports & dashboards (standard REST /analytics resources) ---------
    "list_available_reports",
    "get_report_metadata",
    "execute_report_and_get_results",
    "list_available_dashboards",
    "get_dashboard_data",
    "refresh_dashboard_data",
    # -- Bulk API 2.0 ------------------------------------------------------
    "create_bulk_data_job",
    "upload_csv_to_bulk_job",
    "close_bulk_data_job",
    "abort_bulk_data_job",
    "list_bulk_data_jobs",
    "get_bulk_job_status",
    "get_bulk_job_results",
    # -- files -------------------------------------------------------------
    "upload_file_as_content_version",
    "create_record_attachment",
    "get_blob_field_content",
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    operation: _API for operation in _API_OPERATIONS
}
_REQUIREMENTS["post_message_to_chatter_feed"] = _CHATTER
_REQUIREMENTS["get_chatter_feed_items"] = _CHATTER
_REQUIREMENTS["get_current_user_info"] = _IDENTITY


SALESFORCE_SCOPES = ScopeRegistry(
    provider="salesforce",
    requirements=_REQUIREMENTS,
    # Connect-time only: refresh_token is what makes the token endpoint return a
    # refresh token, so no endpoint implies it.
    extra_scopes={"default": ("refresh_token",)},
)
