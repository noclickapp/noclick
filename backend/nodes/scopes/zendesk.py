"""Zendesk operation → OAuth scope requirements.

Zendesk's OAuth vocabulary is deliberately coarse. The two scopes this node
requests are the *global* ones, documented as: ``read`` "gives access to GET
endpoints. It includes permission to sideload related resources"; ``write``
"gives access to POST, PUT, and DELETE endpoints for creating, updating, and
deleting resources". Zendesk also offers per-resource scopes
(``tickets:read``, ``organizations:write``, ``hc:read``, …) as a *narrower*
alternative, plus ``impersonate``; the node requests neither, and this table
mirrors the vocabulary the node actually asks for. That makes every requirement
here derivable from the HTTP method the operation issues, which is why it is
generated from the call sites rather than hand-transcribed.

Two families sit outside that model:

- **Sunshine Conversations** (``scc_*``) talks to a different host
  (``/sc/v2/apps/{app_id}``) authenticated by an app-scoped Key ID/Secret pair,
  not the OAuth token. No Zendesk OAuth scope applies to them, so they declare
  an empty requirement plus the credential that can run them.
- **Chat** (``/api/v2/chat/*``) has its own scope vocabulary (``read``,
  ``write``, ``chat``) issued by a separate Chat OAuth flow. Zendesk documents
  that "both token types work with the Chat API" but does not say which Support
  scope a Support token needs there, so those five reads are left unmapped
  rather than guessed.

Enforcement is ``SUBSET``: nothing here may shrink the requested list.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: GET endpoints.
_READ = ScopeRequirement(scopes=("read",))
#: POST / PUT / PATCH / DELETE endpoints.
_WRITE = ScopeRequirement(scopes=("write",))
#: Operations that both read and write — notably the webhook triggers, which
#: POST the webhook, GET back Zendesk's generated signing secret (Zendesk
#: refuses a client-supplied one) and DELETE it on teardown.
_READ_WRITE = ScopeRequirement(scopes=("read", "write"))
#: Sunshine Conversations runs on an app-key credential, not the OAuth token.
_SUNSHINE = ScopeRequirement(
    scopes=(),
    credential_types=("zendesk_conversations",),
    note=(
        "Sunshine Conversations uses a separate app-scoped Key ID/Secret "
        "credential; the Zendesk OAuth token cannot reach it."
    ),
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Business Rules ------------------------------------------------------
    "count_view":                            _READ,
    "create_automation":                     _WRITE,
    "create_macro":                          _WRITE,
    "create_sla_policy":                     _WRITE,
    "create_trigger":                        _WRITE,
    "create_view":                           _WRITE,
    "delete_automation":                     _WRITE,
    "delete_macro":                          _WRITE,
    "delete_sla_policy":                     _WRITE,
    "delete_trigger":                        _WRITE,
    "delete_view":                           _WRITE,
    "execute_view":                          _READ,
    "export_view":                           _READ,
    "list_active_automations":               _READ,
    "list_active_macros":                    _READ,
    "list_active_triggers":                  _READ,
    "list_active_views":                     _READ,
    "list_automations":                      _READ,
    "list_macros":                           _READ,
    "list_sla_policies":                     _READ,
    "list_triggers":                         _READ,
    "list_view_tickets":                     _READ,
    "list_views":                            _READ,
    "show_automation":                       _READ,
    "show_macro":                            _READ,
    "show_macro_changes":                    _READ,
    "show_sla_policy":                       _READ,
    "show_ticket_after_macro":               _READ,
    "show_trigger":                          _READ,
    "show_view":                             _READ,
    "update_automation":                     _WRITE,
    "update_macro":                          _WRITE,
    "update_sla_policy":                     _WRITE,
    "update_trigger":                        _WRITE,
    "update_view":                           _WRITE,

    # -- Conversations -------------------------------------------------------
    "scc_accept_control":                    _SUNSHINE,
    "scc_create_conversation":               _SUNSHINE,
    "scc_create_integration":                _SUNSHINE,
    "scc_create_user":                       _SUNSHINE,
    "scc_create_webhook":                    _SUNSHINE,
    "scc_delete_all_messages":               _SUNSHINE,
    "scc_delete_conversation":               _SUNSHINE,
    "scc_delete_message":                    _SUNSHINE,
    "scc_delete_user":                       _SUNSHINE,
    "scc_get_conversation":                  _SUNSHINE,
    "scc_get_user":                          _SUNSHINE,
    "scc_list_conversations":                _SUNSHINE,
    "scc_list_integrations":                 _SUNSHINE,
    "scc_list_messages":                     _SUNSHINE,
    "scc_list_users":                        _SUNSHINE,
    "scc_list_webhooks":                     _SUNSHINE,
    "scc_offer_control":                     _SUNSHINE,
    "scc_pass_control":                      _SUNSHINE,
    "scc_post_activity":                     _SUNSHINE,
    "scc_post_message":                      _SUNSHINE,
    "scc_release_control":                   _SUNSHINE,
    "scc_update_conversation":               _SUNSHINE,
    "scc_update_user":                       _SUNSHINE,

    # -- Custom Objects ------------------------------------------------------
    "count_custom_object_records":           _READ,
    "create_custom_object":                  _WRITE,
    "create_custom_object_field":            _WRITE,
    "create_custom_object_record":           _WRITE,
    "delete_custom_object":                  _WRITE,
    "delete_custom_object_field":            _WRITE,
    "delete_custom_object_record":           _WRITE,
    "list_custom_object_fields":             _READ,
    "list_custom_object_records":            _READ,
    "list_custom_objects":                   _READ,
    "search_custom_object_records":          _READ,
    "show_custom_object":                    _READ,
    "show_custom_object_field":              _READ,
    "show_custom_object_record":             _READ,
    "update_custom_object":                  _WRITE,
    "update_custom_object_field":            _WRITE,
    "update_custom_object_record":           _WRITE,
    "upsert_custom_object_record":           _WRITE,

    # -- Custom Roles --------------------------------------------------------
    "create_custom_role":                    _WRITE,
    "delete_custom_role":                    _WRITE,
    "list_custom_roles":                     _READ,
    "show_custom_role":                      _READ,
    "update_custom_role":                    _WRITE,

    # -- Events --------------------------------------------------------------
    "create_update_profile":                 _WRITE,
    "delete_profile":                        _WRITE,
    "get_user_events":                       _READ,
    "show_profile":                          _READ,
    "track_user_event":                      _WRITE,

    # -- Group Memberships ---------------------------------------------------
    "create_group_membership":               _WRITE,
    "create_many_group_memberships":         _WRITE,
    "delete_group_membership":               _WRITE,
    "list_assignable_group_memberships":     _READ,
    "list_group_memberships":                _READ,
    "list_group_memberships_by_group":       _READ,
    "list_user_group_memberships":           _READ,
    "set_default_group_membership":          _WRITE,
    "show_group_membership":                 _READ,

    # -- Groups --------------------------------------------------------------
    "create_group":                          _WRITE,
    "delete_group":                          _WRITE,
    "list_assignable_groups":                _READ,
    "show_group":                            _READ,
    "update_group":                          _WRITE,

    # -- Help Center ---------------------------------------------------------
    "archive_article":                       _WRITE,
    "create_article":                        _WRITE,
    "create_article_comment":                _WRITE,
    "create_article_label":                  _WRITE,
    "create_article_subscription":           _WRITE,
    "create_category":                       _WRITE,
    "create_section":                        _WRITE,
    "create_section_subscription":           _WRITE,
    "create_translation":                    _WRITE,
    "delete_article_attachment":             _WRITE,
    "delete_article_comment":                _WRITE,
    "delete_article_label":                  _WRITE,
    "delete_article_subscription":           _WRITE,
    "delete_category":                       _WRITE,
    "delete_section":                        _WRITE,
    "delete_section_subscription":           _WRITE,
    "delete_translation":                    _WRITE,
    "guide_search":                          _READ,
    "list_article_attachments":              _READ,
    "list_article_comments":                 _READ,
    "list_article_labels":                   _READ,
    "list_article_subscriptions":            _READ,
    "list_articles":                         _READ,
    "list_categories":                       _READ,
    "list_category_articles":                _READ,
    "list_section_articles":                 _READ,
    "list_section_subscriptions":            _READ,
    "list_sections":                         _READ,
    "list_translations":                     _READ,
    "search_articles":                       _READ,
    "show_article":                          _READ,
    "show_article_attachment":               _READ,
    "show_article_comment":                  _READ,
    "show_category":                         _READ,
    "show_section":                          _READ,
    "update_article":                        _WRITE,
    "update_article_comment":                _WRITE,
    "update_category":                       _WRITE,
    "update_section":                        _WRITE,
    "update_translation":                    _WRITE,

    # -- Metadata ------------------------------------------------------------
    "create_brand":                          _WRITE,
    "create_custom_status":                  _WRITE,
    "create_request":                        _WRITE,
    "create_side_conversation":              _WRITE,
    "create_ticket_field":                   _WRITE,
    "create_ticket_field_option":            _WRITE,
    "create_ticket_form":                    _WRITE,
    "delete_brand":                          _WRITE,
    "delete_ticket_field":                   _WRITE,
    "delete_ticket_field_option":            _WRITE,
    "delete_ticket_form":                    _WRITE,
    "import_many_tickets":                   _WRITE,
    "import_ticket":                         _WRITE,
    "incremental_organizations":             _READ,
    "incremental_ticket_events":             _READ,
    "incremental_users":                     _READ,
    "list_brands":                           _READ,
    "list_custom_statuses":                  _READ,
    "list_groups":                           _READ,
    "list_request_comments":                 _READ,
    "list_requests":                         _READ,
    "list_satisfaction_ratings":             _READ,
    "list_side_conversations":               _READ,
    "list_ticket_field_options":             _READ,
    "list_ticket_fields":                    _READ,
    "list_ticket_forms":                     _READ,
    "reply_side_conversation":               _WRITE,
    "show_brand":                            _READ,
    "show_custom_status":                    _READ,
    "show_job_status":                       _READ,
    "show_request":                          _READ,
    "show_side_conversation":                _READ,
    "show_ticket_field":                     _READ,
    "show_ticket_field_option":              _READ,
    "show_ticket_form":                      _READ,
    "update_brand":                          _WRITE,
    "update_custom_status":                  _WRITE,
    "update_request":                        _WRITE,
    "update_side_conversation":              _WRITE,
    "update_ticket_field":                   _WRITE,
    "update_ticket_field_option":            _WRITE,
    "update_ticket_form":                    _WRITE,

    # -- Organizations -------------------------------------------------------
    "count_organizations":                   _READ,
    "create_many_organization_memberships":  _WRITE,
    "create_many_organizations":             _WRITE,
    "create_or_update_organization":         _WRITE,
    "create_organization":                   _WRITE,
    "create_organization_field":             _WRITE,
    "create_organization_membership":        _WRITE,
    "create_organization_subscription":      _WRITE,
    "delete_organization":                   _WRITE,
    "delete_organization_field":             _WRITE,
    "delete_organization_membership":        _WRITE,
    "delete_organization_subscription":      _WRITE,
    "destroy_many_organizations":            _WRITE,
    "list_organization_fields":              _READ,
    "list_organization_memberships":         _READ,
    "list_organization_subscriptions":       _READ,
    "list_organizations":                    _READ,
    "list_user_organization_memberships":    _READ,
    "merge_organization":                    _WRITE,
    "related_organizations":                 _READ,
    "search_organizations":                  _READ,
    "set_default_organization_membership":   _WRITE,
    "show_many_organizations":               _READ,
    "show_organization":                     _READ,
    "show_organization_field":               _READ,
    "show_organization_membership":          _READ,
    "show_organization_subscription":        _READ,
    "update_many_organizations":             _WRITE,
    "update_organization":                   _WRITE,
    "update_organization_field":             _WRITE,

    # -- Search --------------------------------------------------------------
    "autocomplete_tags":                     _READ,
    "export_search":                         _READ,
    "search":                                _READ,
    "search_count":                          _READ,
    "search_users":                          _READ,

    # -- Sessions ------------------------------------------------------------
    "delete_session":                        _WRITE,
    "list_user_sessions":                    _READ,
    "logout_current_session":                _WRITE,
    "show_current_session":                  _READ,
    "show_session":                          _READ,

    # -- Talk ----------------------------------------------------------------
    "agents_activity":                       _READ,
    "create_voicemail_ticket":               _WRITE,
    "current_queue_activity":                _READ,
    "show_availability":                     _READ,
    "update_availability":                   _WRITE,

    # -- Tickets -------------------------------------------------------------
    "add_comment":                           _WRITE,
    "add_tags":                              _WRITE,
    "count_tickets":                         _READ,
    "create_many_tickets":                   _WRITE,
    "create_satisfaction_rating":            _WRITE,
    "create_ticket":                         _WRITE,
    "delete_ticket":                         _WRITE,
    "destroy_many_tickets":                  _WRITE,
    "list_audits":                           _READ,
    "list_comments":                         _READ,
    "list_incremental_tickets":              _READ,
    "list_organization_tickets":             _READ,
    "list_ticket_tags":                      _READ,
    "list_tickets":                          _READ,
    "list_user_tickets":                     _READ,
    "make_comment_private":                  _WRITE,
    "mark_ticket_as_spam":                   _WRITE,
    "merge_tickets":                         _WRITE,
    "remove_ticket_tags":                    _WRITE,
    "set_ticket_tags":                       _WRITE,
    "show_many_tickets":                     _READ,
    "show_ticket":                           _READ,
    "update_many_tickets":                   _WRITE,
    "update_ticket":                         _WRITE,
    "upload_file":                           _WRITE,

    # -- Triggers ------------------------------------------------------------
    "on_any_ticket_event":                   _READ_WRITE,
    "on_organization_created":               _READ_WRITE,
    "on_organization_deleted":               _READ_WRITE,
    "on_ticket_agent_assignment_changed":    _READ_WRITE,
    "on_ticket_comment_added":               _READ_WRITE,
    "on_ticket_created":                     _READ_WRITE,
    "on_ticket_csat_received":               _READ_WRITE,
    "on_ticket_custom_field_changed":        _READ_WRITE,
    "on_ticket_custom_status_changed":       _READ_WRITE,
    "on_ticket_group_assignment_changed":    _READ_WRITE,
    "on_ticket_merged":                      _READ_WRITE,
    "on_ticket_organization_changed":        _READ_WRITE,
    "on_ticket_priority_changed":            _READ_WRITE,
    "on_ticket_requester_changed":           _READ_WRITE,
    "on_ticket_soft_deleted":                _READ_WRITE,
    "on_ticket_status_changed":              _READ_WRITE,
    "on_ticket_subject_changed":             _READ_WRITE,
    "on_ticket_tags_changed":                _READ_WRITE,
    "on_ticket_type_changed":                _READ_WRITE,
    "on_user_created":                       _READ_WRITE,
    "on_user_deleted":                       _READ_WRITE,

    # -- Users ---------------------------------------------------------------
    "autocomplete_users":                    _READ,
    "bulk_delete_users":                     _WRITE,
    "count_users":                           _READ,
    "create_identity":                       _WRITE,
    "create_many_users":                     _WRITE,
    "create_or_update_many_users":           _WRITE,
    "create_or_update_user":                 _WRITE,
    "create_user":                           _WRITE,
    "create_user_field":                     _WRITE,
    "create_user_field_option":              _WRITE,
    "delete_identity":                       _WRITE,
    "delete_user":                           _WRITE,
    "delete_user_field":                     _WRITE,
    "delete_user_field_option":              _WRITE,
    "list_identities":                       _READ,
    "list_user_field_options":               _READ,
    "list_user_fields":                      _READ,
    "list_users":                            _READ,
    "list_users_by_group":                   _READ,
    "list_users_by_organization":            _READ,
    "make_identity_primary":                 _WRITE,
    "merge_end_users":                       _WRITE,
    "permanently_delete_user":               _WRITE,
    "request_identity_verification":         _WRITE,
    "show_identity":                         _READ,
    "show_many_users":                       _READ,
    "show_self":                             _READ,
    "show_user":                             _READ,
    "show_user_field":                       _READ,
    "show_user_related":                     _READ,
    "update_identity":                       _WRITE,
    "update_many_users":                     _WRITE,
    "update_user":                           _WRITE,
    "update_user_field":                     _WRITE,
    "update_user_field_option":              _WRITE,
    "verify_identity":                       _WRITE,

    # -- Webhooks ------------------------------------------------------------
    "clone_webhook":                         _WRITE,
    "create_webhook":                        _WRITE,
    "delete_webhook":                        _WRITE,
    "list_webhook_invocation_attempts":      _READ,
    "list_webhook_invocations":              _READ,
    "list_webhooks":                         _READ,
    "patch_webhook":                         _WRITE,
    "reset_webhook_signing_secret":          _WRITE,
    "show_webhook":                          _READ,
    "show_webhook_signing_secret":           _READ,
    "test_webhook":                          _WRITE,
    "update_webhook":                        _WRITE,
}

ZENDESK_SCOPES = ScopeRegistry(
    provider="zendesk",
    requirements=_REQUIREMENTS,
    unmapped=(
        # Chat API (/api/v2/chat/*). It carries its own scope vocabulary from a
        # separate Chat OAuth flow; Zendesk does not document what a Support
        # OAuth token needs to reach it. All five are reads, so the likely
        # answer is the `read` this node already requests — but "likely" is how
        # unusable operations ship, so they stay unmapped until confirmed.
        "list_agents",
        "list_chats",
        "list_departments",
        "show_agent",
        "show_chat",
    ),
)
