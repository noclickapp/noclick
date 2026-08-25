"""PagerDuty operation → OAuth scope requirements.

PagerDuty scopes are ``<resource>.read`` / ``<resource>.write``, with a few
namespaced under their parent resource (``users:contact_methods.write``,
``incident_workflows:instances.write``). A classic app can also hold the coarse
legacy ``read``/``write``, but NoClick's app is scoped, so every call needs the
granular scope for the endpoint it hits or PagerDuty answers 403 "Token missing
required scopes".

This table is derived from PagerDuty's published OpenAPI schema
(``PagerDuty/api-schema``, ``reference/REST/openapiv3.json``), whose
``x-pd-requires-scope`` on each path+method is the same string its API
reference prints as "Scoped OAuth requires:". Each operation maps to the union
of the scopes its handler's endpoints require — ``add_responders`` looks a user
up before writing, so it needs both ``users.read`` and ``incidents.write``.

Two families need no scope at all: the Events API (``send_event``,
``send_change_event``) authenticates with an integration routing key in the body
rather than the OAuth token, and ``GET /users/me`` carries no
``x-pd-requires-scope`` — it identifies the token holder.

Enforcement is ``SUBSET``: nothing here may shrink the requested list. What
remains in ``unmapped`` is undocumented rather than unrequested — PagerDuty
publishes no scope for it at all.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


#: Events API v2 authenticates with an integration routing key in the request
#: body, so the OAuth token's scopes are irrelevant to it.
_ROUTING_KEY = ScopeRequirement(
    scopes=(),
    note="Uses the integration routing key from the node config, not the OAuth token.",
)
#: GET /users/me — identifies the token holder; PagerDuty documents no scope.
_TOKEN_IDENTITY = ScopeRequirement(scopes=())


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Add-ons -----------------------------------------------------------
    "create_addon":                         _s("addons.write"),
    "delete_addon":                         _s("addons.write"),
    "get_addon":                            _s("addons.read"),
    "list_addons":                          _s("addons.read"),
    "update_addon":                         _s("addons.write"),

    # -- Analytics ---------------------------------------------------------
    "analytics_incident_metrics":           _s("analytics.write"),
    "analytics_incident_metrics_by_dimension": _s("analytics.write"),
    "analytics_raw_incidents":              _s("analytics.write"),
    "analytics_responder_metrics":          _s("analytics.write"),
    "get_raw_incident":                     _s("analytics.read"),
    "get_raw_incident_responses":           _s("analytics.read"),

    # -- Audit -------------------------------------------------------------
    "list_audit_records":                   _s("audit_records.read"),

    # -- Business Services -------------------------------------------------
    "create_business_service":              _s("services.write"),
    "create_business_service_subscribers":  _s("subscribers.write"),
    "delete_business_service":              _s("services.write"),
    "delete_priority_thresholds":           _s("services.write"),
    "get_business_service":                 _s("services.read"),
    "get_priority_thresholds":              _s("services.read"),
    "list_business_service_impactors":      _s("services.read"),
    "list_business_service_impacts":        _s("services.read"),
    "list_business_service_subscribers":    _s("subscribers.read"),
    "list_business_services":               _s("services.read"),
    "remove_business_service_subscribers":  _s("subscribers.write"),
    "set_priority_threshold":               _s("services.write"),
    "update_business_service":              _s("services.write"),

    # -- Contact Methods & Notification Rules ------------------------------
    # Notification rules hang off the same scope pair as contact methods
    # (/users/{id}/notification_rules carries users:contact_methods.*).
    "create_contact_method":                _s("users:contact_methods.write"),
    "create_notification_rule":             _s("users:contact_methods.write"),
    "delete_contact_method":                _s("users:contact_methods.write"),
    "delete_notification_rule":             _s("users:contact_methods.write"),
    "get_contact_method":                   _s("users:contact_methods.read"),
    "get_notification_rule":                _s("users:contact_methods.read"),
    "list_contact_methods":                 _s("users:contact_methods.read"),
    "list_notification_rules":              _s("users:contact_methods.read"),
    "update_contact_method":                _s("users:contact_methods.write"),
    "update_notification_rule":             _s("users:contact_methods.write"),

    # -- Change Events -----------------------------------------------------
    "list_change_events":                   _s("change_events.read"),
    "list_service_change_events":           _s("services.read"),
    "send_change_event":                    _ROUTING_KEY,

    # -- Custom Fields -----------------------------------------------------
    "create_custom_field":                  _s("custom_fields.write"),
    "create_field_option":                  _s("custom_fields.write"),
    "delete_custom_field":                  _s("custom_fields.write"),
    "delete_field_option":                  _s("custom_fields.write"),
    "get_custom_field":                     _s("custom_fields.read"),
    "get_field_option":                     _s("custom_fields.read"),
    "list_custom_fields":                   _s("custom_fields.read"),
    "list_field_options":                   _s("custom_fields.read"),
    "update_custom_field":                  _s("custom_fields.write"),
    "update_field_option":                  _s("custom_fields.write"),

    # -- Escalation Policies -----------------------------------------------
    "create_escalation_policy":             _s("escalation_policies.write"),
    "delete_escalation_policy":             _s("escalation_policies.write"),
    "get_escalation_policy":                _s("escalation_policies.read"),
    "list_escalation_policies":             _s("escalation_policies.read"),
    "update_escalation_policy":             _s("escalation_policies.write"),

    # -- Event Orchestrations ----------------------------------------------
    "create_event_orchestration":           _s("event_orchestrations.write"),
    "create_orchestration_integration":     _s("event_orchestrations.write"),
    "delete_event_orchestration":           _s("event_orchestrations.write"),
    "delete_orchestration_integration":     _s("event_orchestrations.write"),
    "get_event_orchestration":              _s("event_orchestrations.read"),
    "get_orchestration_global":             _s("event_orchestrations.read"),
    "get_orchestration_integration":        _s("event_orchestrations.read"),
    "get_orchestration_router":             _s("event_orchestrations.read"),
    "get_service_orchestration":            _s("services.read"),
    "get_service_orchestration_active":     _s("services.read"),
    "list_event_orchestrations":            _s("event_orchestrations.read"),
    "list_orchestration_integrations":      _s("event_orchestrations.read"),
    "set_service_orchestration_active":     _s("services.write"),
    "update_event_orchestration":           _s("event_orchestrations.write"),
    "update_orchestration_global":          _s("event_orchestrations.write"),
    "update_orchestration_integration":     _s("event_orchestrations.write"),
    "update_orchestration_router":          _s("event_orchestrations.write"),
    "update_service_orchestration":         _s("services.write"),

    # -- Event Rulesets (legacy) -------------------------------------------
    # Predecessor of Event Orchestrations, with its own scope pair —
    # event_orchestrations.* does not reach /rulesets.
    "create_ruleset":                       _s("event_rules.write"),
    "create_ruleset_rule":                  _s("event_rules.write"),
    "delete_ruleset":                       _s("event_rules.write"),
    "delete_ruleset_rule":                  _s("event_rules.write"),
    "get_ruleset":                          _s("event_rules.read"),
    "get_ruleset_rule":                     _s("event_rules.read"),
    "list_ruleset_rules":                   _s("event_rules.read"),
    "list_rulesets":                        _s("event_rules.read"),
    "update_ruleset":                       _s("event_rules.write"),
    "update_ruleset_rule":                  _s("event_rules.write"),

    # -- Events API --------------------------------------------------------
    "send_event":                           _ROUTING_KEY,

    # -- Extensions --------------------------------------------------------
    "create_extension":                     _s("extensions.write"),
    "delete_extension":                     _s("extensions.write"),
    "enable_extension":                     _s("extensions.write"),
    "get_extension":                        _s("extensions.read"),
    "get_extension_schema":                 _s("extension_schemas.read"),
    "list_extension_schemas":               _s("extension_schemas.read"),
    "list_extensions":                      _s("extensions.read"),
    "update_extension":                     _s("extensions.write"),

    # -- Incident Details --------------------------------------------------
    "add_responders":                       _s("incidents.write", "users.read"),
    "add_status_update_subscribers":        _s("subscribers.write"),
    "create_note":                          _s("incidents.write"),
    "create_status_update":                 _s("incidents.write"),
    "get_alert":                            _s("incidents.read"),
    "get_incident_custom_fields":           _s("incidents.read"),
    "get_log_entry":                        _s("incidents.read"),
    "get_outlier_incident":                 _s("incidents.read"),
    "get_past_incidents":                   _s("incidents.read"),
    "get_related_incidents":                _s("incidents.read"),
    "list_alerts":                          _s("incidents.read"),
    "list_global_log_entries":              _s("incidents.read"),
    "list_log_entries":                     _s("incidents.read"),
    "list_notes":                           _s("incidents.read"),
    "list_related_change_events":           _s("incidents.read"),
    "list_status_update_subscribers":       _s("subscribers.read"),
    "manage_alerts":                        _s("incidents.write"),
    "remove_status_update_subscriber":      _s("subscribers.write"),
    "update_alert":                         _s("incidents.write"),
    "update_incident_custom_fields":        _s("incidents.write"),

    # -- Incident Workflows ------------------------------------------------
    "create_incident_workflow":             _s("incident_workflows.write"),
    "delete_incident_workflow":             _s("incident_workflows.write"),
    "get_incident_workflow":                _s("incident_workflows.read"),
    "list_incident_workflows":              _s("incident_workflows.read"),
    # POST /incident_workflows/{id}/instances is namespaced under its parent.
    "start_incident_workflow":              _s("incident_workflows:instances.write"),
    "update_incident_workflow":             _s("incident_workflows.write"),

    # -- Incidents ---------------------------------------------------------
    "create_incident":                      _s("incidents.write"),
    "get_incident":                         _s("incidents.read"),
    "list_incidents":                       _s("incidents.read"),
    "manage_incidents":                     _s("incidents.write"),
    "merge_incidents":                      _s("incidents.write"),
    "snooze_incident":                      _s("incidents.write"),
    "update_incident":                      _s("incidents.write"),

    # -- Maintenance Windows -----------------------------------------------
    "create_maintenance_window":            _s("services.write"),
    "delete_maintenance_window":            _s("services.write"),
    "get_maintenance_window":               _s("services.read"),
    "list_maintenance_windows":             _s("services.read"),
    "update_maintenance_window":            _s("services.write"),

    # -- Reference ---------------------------------------------------------
    "list_abilities":                       _s("abilities.read"),
    "list_license_allocations":             _s("licenses.read"),
    "list_licenses":                        _s("licenses.read"),
    "list_priorities":                      _s("priorities.read"),
    "paused_incident_report_alerts":        _s("incidents.read"),
    "paused_incident_report_counts":        _s("incidents.read"),
    "test_ability":                         _s("abilities.read"),

    # -- Schedules & On-Call -----------------------------------------------
    "create_override":                      _s("schedules.write"),
    "create_schedule":                      _s("schedules.write"),
    "delete_override":                      _s("schedules.write"),
    "delete_schedule":                      _s("schedules.write"),
    "get_schedule":                         _s("schedules.read"),
    "list_oncalls":                         _s("oncalls.read"),
    "list_overrides":                       _s("schedules.read"),
    "list_schedules":                       _s("schedules.read"),
    "list_users_on_schedule":               _s("users.read"),
    "preview_schedule":                     _s("schedules.write"),
    "update_schedule":                      _s("schedules.write"),

    # -- Service Dependencies ----------------------------------------------
    "associate_service_dependencies":       _s("services.write"),
    "disassociate_service_dependencies":    _s("services.write"),
    "get_business_service_dependencies":    _s("services.read"),
    "get_technical_service_dependencies":   _s("services.read"),

    # -- Service Event Rules -----------------------------------------------
    "create_service_event_rule":            _s("services.write"),
    "delete_service_event_rule":            _s("services.write"),
    "get_service_event_rule":               _s("services.read"),
    "list_service_event_rules":             _s("services.read"),
    "update_service_event_rule":            _s("services.write"),

    # -- Service Integrations ----------------------------------------------
    "create_service_integration":           _s("services.write"),
    "get_service_integration":              _s("services.read"),
    "update_service_integration":           _s("services.write"),

    # -- Services ----------------------------------------------------------
    "create_service":                       _s("services.write"),
    "delete_service":                       _s("services.write"),
    "get_service":                          _s("services.read"),
    "list_services":                        _s("services.read"),
    "update_service":                       _s("services.write"),

    # -- Status Dashboards -------------------------------------------------
    "get_status_dashboard":                 _s("status_dashboards.read"),
    "get_status_dashboard_by_slug":         _s("status_dashboards.read"),
    "get_status_dashboard_service_impacts": _s("status_dashboards.read"),
    "list_status_dashboards":               _s("status_dashboards.read"),

    # -- Status Pages ------------------------------------------------------
    "create_status_page_post":              _s("status_pages.write"),
    "create_status_page_post_update":       _s("status_pages.write"),
    "create_status_page_subscription":      _s("status_pages.write"),
    "delete_status_page_post":              _s("status_pages.write"),
    "delete_status_page_post_update":       _s("status_pages.write"),
    "delete_status_page_subscription":      _s("status_pages.write"),
    "get_status_page_post":                 _s("status_pages.read"),
    "get_status_page_post_update":          _s("status_pages.read"),
    "get_status_page_subscription":         _s("status_pages.read"),
    "list_status_page_post_updates":        _s("status_pages.read"),
    "list_status_page_posts":               _s("status_pages.read"),
    "list_status_page_subscriptions":       _s("status_pages.read"),
    "list_status_pages":                    _s("status_pages.read"),
    "update_status_page_post":              _s("status_pages.write"),
    "update_status_page_post_update":       _s("status_pages.write"),

    # -- Tags --------------------------------------------------------------
    "change_tags":                          _s("tags.write"),
    "create_tag":                           _s("tags.write"),
    "delete_tag":                           _s("tags.write"),
    "get_tag":                              _s("tags.read"),
    "get_tags_for_entity":                  _s("tags.read"),
    "list_tags":                            _s("tags.read"),

    # -- Templates ---------------------------------------------------------
    "create_template":                      _s("templates.write"),
    "delete_template":                      _s("templates.write"),
    "get_template":                         _s("templates.read"),
    "list_templates":                       _s("templates.read"),
    "render_template":                      _s("templates.read"),
    "update_template":                      _s("templates.write"),

    # -- Triggers ----------------------------------------------------------
    "on_incident_event":                    _s("webhook_subscriptions.write"),

    # -- Users & Teams -----------------------------------------------------
    "add_team_member":                      _s("teams.write"),
    "associate_team_escalation_policy":     _s("teams.write"),
    "create_team":                          _s("teams.write"),
    "create_user":                          _s("users.write"),
    "delete_team":                          _s("teams.write"),
    "delete_user":                          _s("users.write"),
    "get_current_user":                     _TOKEN_IDENTITY,
    "get_team":                             _s("teams.read"),
    "get_user":                             _s("users.read"),
    "list_team_members":                    _s("teams.read"),
    "list_teams":                           _s("teams.read"),
    "list_users":                           _s("users.read"),
    "remove_team_escalation_policy":        _s("teams.write"),
    "remove_team_member":                   _s("teams.write"),
    "update_team":                          _s("teams.write"),
    "update_user":                          _s("users.write"),

    # -- Vendors -----------------------------------------------------------
    "get_vendor":                           _s("vendors.read"),
    "list_vendors":                         _s("vendors.read"),

    # -- Webhooks ----------------------------------------------------------
    "create_webhook_subscription":          _s("webhook_subscriptions.write"),
    "delete_webhook_subscription":          _s("webhook_subscriptions.write"),
    "disable_webhook_subscription":         _s("webhook_subscriptions.write"),
    "enable_webhook_subscription":          _s("webhook_subscriptions.write"),
    "get_webhook_subscription":             _s("webhook_subscriptions.read"),
    "list_webhook_subscriptions":           _s("webhook_subscriptions.read"),
    "ping_webhook_subscription":            _s("webhook_subscriptions.write"),
    "update_webhook_subscription":          _s("webhook_subscriptions.write"),

    # -- Workflow Triggers -------------------------------------------------
    "associate_trigger_service":            _s("incident_workflows.write"),
    "create_incident_workflow_trigger":     _s("incident_workflows.write"),
    "delete_incident_workflow_trigger":     _s("incident_workflows.write"),
    "disassociate_trigger_service":         _s("incident_workflows.write"),
    "get_incident_workflow_trigger":        _s("incident_workflows.read"),
    "list_incident_workflow_triggers":      _s("incident_workflows.read"),
    "update_incident_workflow_trigger":     _s("incident_workflows.write"),
}

PAGERDUTY_SCOPES = ScopeRegistry(
    provider="pagerduty",
    requirements=_REQUIREMENTS,
    unmapped=(
        # GET /notifications is stamped users:notifications.read in the OpenAPI
        # schema, but the app-registration console offers no row granting it
        # (verified 2026-07-22) — requesting it would break connect outright.
        "list_notifications",
        # Automation Actions has no `x-pd-requires-scope` in PagerDuty's published
        # OpenAPI schema and no scope named in its API reference, so what a scoped
        # OAuth token needs here is genuinely unknown.
        "create_automation_action",
        "create_runner",
        "delete_automation_action",
        "delete_runner",
        "get_automation_action",
        "get_invocation",
        "get_runner",
        "invoke_automation_action",
        "list_automation_actions",
        "list_invocations",
        "list_runners",
        "update_automation_action",
        "update_runner",

        # Response Plays are absent from PagerDuty's published OpenAPI schema
        # (plan-gated / classic), so no scope is documented for them.
        "create_response_play",
        "delete_response_play",
        "get_response_play",
        "list_response_plays",
        "run_response_play",
        "update_response_play",
    ),
)
