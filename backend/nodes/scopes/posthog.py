"""PostHog operation → OAuth scope requirements.

PostHog scopes are ``<scope_object>:read`` / ``<scope_object>:write`` pairs over
the objects in ``posthog/scopes.py:APIScopeObject``. The requirement for a REST
call is derived by ``APIScopePermission`` from the viewset's ``scope_object``
plus the DRF action: ``list``/``retrieve`` → ``:read``, ``create``/``update``/
``partial_update``/``patch``/``destroy`` → ``:write``. Custom ``@action``
endpoints do NOT follow that rule — they must name ``required_scopes``
explicitly, and an action that names none rejects personal-API-key and OAuth
tokens outright, so each one here was read off the viewset rather than guessed.

Three quirks shape the table:

- **Ingestion is unscoped.** ``capture_event`` / ``batch_capture`` / ``identify``
  / ``group_identify`` / ``evaluate_flags`` post to the ingestion host with the
  PROJECT API key in the body and no bearer token (``_ingest_request``), so no
  OAuth scope is involved at all.
- **Events are a query scope.** ``EventViewSet.scope_object == "query"``, so
  ``list_events`` needs ``query:read``, not an ``event`` scope. Likewise
  ``QueryViewSet`` lists ``create`` among its READ actions, so running a query
  is ``query:read``.
- **Deletes are often PATCHes.** The node soft-deletes flags, insights,
  dashboards, cohorts, annotations and destinations with ``PATCH {deleted:
  true}``, which is ``partial_update`` → the same ``:write`` scope as an update.

Trigger operations (``on_pageview`` and friends) never call the API at run time;
they register a webhook *destination* — ``POST hog_functions/`` — so their
requirement is ``hog_function:write``.

Sources: https://posthog.com/docs/api plus the viewsets in the PostHog repo
(``posthog/permissions.py``, ``posthog/api/*.py``, ``products/*/backend/api/*.py``).
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


#: Ingestion endpoints authenticate with the project API key, not the token.
_INGESTION = _s()

_QUERY_READ = _s("query:read")
_FLAG_READ = _s("feature_flag:read")
_FLAG_WRITE = _s("feature_flag:write")
_PERSON_READ = _s("person:read")
_PERSON_WRITE = _s("person:write")
_COHORT_READ = _s("cohort:read")
_COHORT_WRITE = _s("cohort:write")
_ANNOTATION_READ = _s("annotation:read")
_ANNOTATION_WRITE = _s("annotation:write")
_INSIGHT_READ = _s("insight:read")
_INSIGHT_WRITE = _s("insight:write")
_DASHBOARD_READ = _s("dashboard:read")
_DASHBOARD_WRITE = _s("dashboard:write")
_ACTION_READ = _s("action:read")
_ACTION_WRITE = _s("action:write")
_SURVEY_READ = _s("survey:read")
_SURVEY_WRITE = _s("survey:write")
_RECORDING_READ = _s("session_recording:read")
_GROUP_READ = _s("group:read")
_EXPERIMENT_READ = _s("experiment:read")
_EXPERIMENT_WRITE = _s("experiment:write")
_NOTEBOOK_READ = _s("notebook:read")
_NOTEBOOK_WRITE = _s("notebook:write")
_EAF_READ = _s("early_access_feature:read")
_EAF_WRITE = _s("early_access_feature:write")
_BATCH_EXPORT_READ = _s("batch_export:read")
_HOG_FUNCTION_READ = _s("hog_function:read")
_HOG_FUNCTION_WRITE = _s("hog_function:write")


_TRIGGER_OPERATIONS = (
    "on_pageview",
    "on_pageleave",
    "on_autocapture",
    "on_rageclick",
    "on_screen",
    "on_identify",
    "on_group_identify",
    "on_set_person_properties",
    "on_feature_flag_called",
    "on_exception",
    "on_survey_shown",
    "on_survey_sent",
    "on_survey_dismissed",
    "on_web_vitals",
    "on_custom_event",
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Ingestion (project API key, no bearer token) --------------------
    "capture_event": _INGESTION,
    "batch_capture": _INGESTION,
    "identify": _INGESTION,
    "group_identify": _INGESTION,
    "evaluate_flags": _INGESTION,
    # -- Query / events --------------------------------------------------
    # QueryViewSet.scope_object_read_actions includes "create".
    "run_query": _QUERY_READ,
    # EventViewSet.scope_object == "query".
    "list_events": _QUERY_READ,
    # -- Feature flags ---------------------------------------------------
    "list_feature_flags": _FLAG_READ,
    "get_feature_flag": _FLAG_READ,
    "list_my_feature_flags": _FLAG_READ,  # @action required_scopes=["feature_flag:read"]
    "create_feature_flag": _FLAG_WRITE,
    "update_feature_flag": _FLAG_WRITE,
    "delete_feature_flag": _FLAG_WRITE,  # PATCH {deleted: true}
    # -- Persons ---------------------------------------------------------
    "list_persons": _PERSON_READ,
    "get_person": _PERSON_READ,
    "update_person": _PERSON_WRITE,
    "delete_person": _PERSON_WRITE,
    "split_person": _PERSON_WRITE,  # @action required_scopes=["person:write"]
    "bulk_delete_persons": _PERSON_WRITE,  # @action required_scopes=["person:write"]
    # -- Cohorts ---------------------------------------------------------
    "list_cohorts": _COHORT_READ,
    "get_cohort": _COHORT_READ,
    "create_cohort": _COHORT_WRITE,
    "update_cohort": _COHORT_WRITE,
    "delete_cohort": _COHORT_WRITE,  # PATCH {deleted: true}
    # @action required_scopes=["cohort:read", "person:read"]
    "list_cohort_persons": _s("cohort:read", "person:read"),
    # @action required_scopes=["cohort:write"]
    "add_persons_to_cohort": _COHORT_WRITE,
    # -- Annotations ------------------------------------------------------
    "list_annotations": _ANNOTATION_READ,
    "create_annotation": _ANNOTATION_WRITE,
    "update_annotation": _ANNOTATION_WRITE,
    "delete_annotation": _ANNOTATION_WRITE,  # PATCH {deleted: true}
    # -- Insights ---------------------------------------------------------
    "list_insights": _INSIGHT_READ,
    "get_insight": _INSIGHT_READ,
    "create_insight": _INSIGHT_WRITE,
    "update_insight": _INSIGHT_WRITE,
    "delete_insight": _INSIGHT_WRITE,  # PATCH {deleted: true}
    # -- Dashboards -------------------------------------------------------
    "list_dashboards": _DASHBOARD_READ,
    "get_dashboard": _DASHBOARD_READ,
    "create_dashboard": _DASHBOARD_WRITE,
    "update_dashboard": _DASHBOARD_WRITE,
    "delete_dashboard": _DASHBOARD_WRITE,  # PATCH {deleted: true}
    # -- Actions ----------------------------------------------------------
    "list_actions": _ACTION_READ,
    "get_action": _ACTION_READ,
    "create_action": _ACTION_WRITE,
    # -- Surveys ----------------------------------------------------------
    "list_surveys": _SURVEY_READ,
    "get_survey": _SURVEY_READ,
    "create_survey": _SURVEY_WRITE,
    "update_survey": _SURVEY_WRITE,
    # launch/stop: @action required_scopes=["survey:write"]
    "survey_action": _SURVEY_WRITE,
    # survey_responses_list: @action required_scopes=["survey:read", "query:read"]
    "get_survey_responses": _s("survey:read", "query:read"),
    # survey_stats: @action required_scopes=["survey:read"]
    "get_survey_stats": _SURVEY_READ,
    # -- Session recordings -----------------------------------------------
    "list_session_recordings": _RECORDING_READ,
    "get_session_recording": _RECORDING_READ,
    # scope_object_read_actions is ["list", "retrieve", "snapshots"], so
    # `destroy` falls through to the default write action.
    "delete_session_recording": _s("session_recording:write"),
    # -- Groups -------------------------------------------------------------
    "list_group_types": _GROUP_READ,
    "list_groups": _GROUP_READ,
    "find_group": _GROUP_READ,  # @action required_scopes=["group:read"]
    # -- Organization members / invites --------------------------------------
    # OrganizationMemberViewSet / OrganizationInviteViewSet
    # scope_object == "organization_member".
    "list_org_members": _s("organization_member:read"),
    "list_org_invites": _s("organization_member:read"),
    "create_org_invite": _s("organization_member:write"),
    # -- Experiments -------------------------------------------------------
    "list_experiments": _EXPERIMENT_READ,
    "get_experiment": _EXPERIMENT_READ,
    "create_experiment": _EXPERIMENT_WRITE,
    "update_experiment": _EXPERIMENT_WRITE,
    # launch/pause/resume/end/archive/reset/duplicate all resolve to
    # experiment:write; the extra feature_flag:write / task:write branches in
    # dangerously_get_required_scopes only trigger on disable_feature_flag /
    # open_cleanup_pr, which this node never sends.
    "experiment_action": _EXPERIMENT_WRITE,
    # -- Data management ----------------------------------------------------
    "list_event_definitions": _s("event_definition:read"),
    "list_property_definitions": _s("property_definition:read"),
    # -- Notebooks ----------------------------------------------------------
    "list_notebooks": _NOTEBOOK_READ,
    "get_notebook": _NOTEBOOK_READ,
    "create_notebook": _NOTEBOOK_WRITE,
    # -- Early access features -----------------------------------------------
    "list_early_access_features": _EAF_READ,
    "create_early_access_feature": _EAF_WRITE,
    # -- Batch exports --------------------------------------------------------
    "list_batch_exports": _BATCH_EXPORT_READ,
    "get_batch_export": _BATCH_EXPORT_READ,
    # -- Destinations (hog functions) ------------------------------------------
    "list_destinations": _HOG_FUNCTION_READ,
    "get_destination": _HOG_FUNCTION_READ,
    "list_destination_templates": _HOG_FUNCTION_READ,  # scope_object == "hog_function"
    # "logs" / "metrics_totals" are in scope_object_read_actions.
    "get_destination_logs": _HOG_FUNCTION_READ,
    "get_destination_metrics": _HOG_FUNCTION_READ,
    "create_destination": _HOG_FUNCTION_WRITE,
    "update_destination": _HOG_FUNCTION_WRITE,
    "set_destination_enabled": _HOG_FUNCTION_WRITE,
    "delete_destination": _HOG_FUNCTION_WRITE,  # PATCH {deleted: true}
    # -- Activity log / org ------------------------------------------------------
    "list_activity_log": _s("activity_log:read"),
    "list_projects": _s("project:read"),
    "list_roles": _s("organization:read"),  # RoleViewSet.scope_object == "organization"
    # -- Triggers: registration creates a webhook destination ---------------------
    **{operation: _HOG_FUNCTION_WRITE for operation in _TRIGGER_OPERATIONS},
}


POSTHOG_SCOPES = ScopeRegistry(
    provider="posthog",
    requirements=_REQUIREMENTS,
    unmapped=(
        # Genuinely undeterminable, not missing:
        # /api/feature_flag/local_evaluation/ is not a project-scoped viewset
        # action and PostHog does not document a scope for it.
        "feature_flag_local_evaluation",
        # Arbitrary user-supplied method + path — the scope is whatever the
        # target endpoint needs and cannot be known statically.
        "raw_request",
    ),
    extra_scopes={
        # Every management operation auto-resolves the project when the
        # credential has no project_id: GET /api/organizations/@current/projects/
        # then GET /api/users/@me/ as the team-scoped-key fallback. No single
        # operation implies them.
        "default": ("project:read", "user:read"),
    },
)
