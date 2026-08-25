"""HubSpot operation → OAuth scope requirements.

HubSpot's scopes are unusually granular — one pair per CRM object
(``crm.objects.<object>.read`` / ``.write``), plus a scope per product area
(``content``, ``hubdb``, ``files``, ``automation``, ``conversations.*``,
``settings.users.*``, ``crm.lists.*``, …). Mapped against the published list
(https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes)
and each operation's API family, taken from the endpoint the handler calls.

**This node requests eight scopes and has 254 operations.** Only contacts,
companies, deals and tickets are covered; the rest of the surface — CMS, HubDB,
files, marketing, automation, conversations, settings, and every non-core CRM
object — needs scopes the node never asks for. Those operations are listed in
``unmapped`` under a ``MISSING SCOPE`` comment naming the exact scope. This is
the Slack bug recurring: they can only ever fail.

Three things worth knowing before extending the table:

- **Engagements ride the contacts scopes.** Notes, calls, emails, meetings and
  tasks are gated by ``crm.objects.contacts.read`` / ``.write``, not by a scope
  of their own (confirmed on HubSpot's engagements reference). That is why 30 of
  the 67 mapped operations are activities.
- **Tickets use the legacy combined ``tickets`` scope**, which grants read AND
  write — there is no ``crm.objects.tickets.read`` in the published list.
- **Object-generic operations cannot be mapped statically.** Batch record ops,
  associations, properties and pipelines all take an ``object_type`` config
  field, so the scope depends on a value chosen at run time. They sit in
  ``unmapped`` with a note rather than a scope string; only a per-object check at
  the call site could declare them honestly.

Trigger operations subscribe to HubSpot webhook events, which require the read
scope for the subscribed object type.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_CONTACTS_R = "crm.objects.contacts.read"
_CONTACTS_W = "crm.objects.contacts.write"
_COMPANIES_R = "crm.objects.companies.read"
_COMPANIES_W = "crm.objects.companies.write"
_DEALS_R = "crm.objects.deals.read"
_DEALS_W = "crm.objects.deals.write"
_TICKETS = "tickets"  # legacy combined scope: grants read AND write


# op names grouped by the scope set they need, keyed by that set.
_BY_SCOPES: dict[tuple[str, ...], tuple[str, ...]] = {
    (_CONTACTS_R,): (
        "get_contact",
        "list_contacts",
        "search_contacts",
        # Engagements are gated by the CONTACTS scopes, not one of their own.
        "get_call_activity",
        "list_call_activities",
        "search_call_activities",
        "get_email_activity",
        "list_email_activities",
        "search_email_activities",
        "get_meeting_activity",
        "list_meeting_activities",
        "search_meeting_activities",
        "get_note_activity",
        "list_note_activities",
        "search_note_activities",
        "get_task_activity",
        "list_task_activities",
        "search_task_activities",
        # webhook subscriptions deliver only objects the app can read
        "on_contact_created",
        "on_contact_updated",
        "on_contact_deleted",
    ),
    (_CONTACTS_W,): (
        "create_contact",
        "update_contact",
        "delete_contact",
        "create_call_activity",
        "update_call_activity",
        "delete_call_activity",
        "create_email_activity",
        "update_email_activity",
        "delete_email_activity",
        "create_meeting_activity",
        "update_meeting_activity",
        "delete_meeting_activity",
        "create_note_activity",
        "update_note_activity",
        "delete_note_activity",
        "create_task_activity",
        "update_task_activity",
        "delete_task_activity",
    ),
    (_COMPANIES_R,): (
        "get_company",
        "list_companies",
        "search_companies",
        "on_company_created",
    ),
    (_COMPANIES_W,): (
        "create_company",
        "update_company",
        "delete_company",
    ),
    (_DEALS_R,): (
        "get_deal",
        "list_deals",
        "search_deals",
        "on_deal_created",
        "on_deal_updated",
    ),
    (_DEALS_W,): (
        "create_deal",
        "update_deal",
        "delete_deal",
    ),
    (_TICKETS,): (
        "create_support_ticket",
        "get_support_ticket",
        "list_support_tickets",
        "search_support_tickets",
        "update_support_ticket",
        "delete_support_ticket",
        "on_ticket_created",
    ),
}

# The `/oauth/v1/*` endpoints authenticate with the token (or the client
# credentials) they are called about, so they are not scope-gated.
_NO_SCOPE: tuple[str, ...] = (
    "get_access_token_info",
    "validate_access_token",
    "refresh_access_token",
    "revoke_access_token",
    "list_api_scopes",
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    operation: _s(*scopes)
    for scopes, operations in _BY_SCOPES.items()
    for operation in operations
}
_REQUIREMENTS.update({operation: _s() for operation in _NO_SCOPE})
# Account info (`/integrations/v1/me`) is the one endpoint gated by `oauth`.
_REQUIREMENTS["get_account_info"] = _s("oauth")


HUBSPOT_SCOPES = ScopeRegistry(
    provider="hubspot",
    requirements=_REQUIREMENTS,
    # Required of every HubSpot app; no single endpoint implies it.
    extra_scopes={"default": ("oauth",)},
    unmapped=(
        # -- object type is a RUNTIME config field, so the required scope is
        # not knowable statically. Each needs crm.objects.<object>.read/write
        # (or crm.schemas.<object>.* for properties) for whatever the user
        # picks; only the contacts/companies/deals choices are covered today.
        "batch_create_records",
        "batch_read_records",
        "batch_update_records",
        "batch_archive_records",
        "batch_upsert_records",
        "create_record_association",
        "delete_record_association",
        "list_record_associations",
        "create_custom_property",
        "get_custom_property",
        "list_custom_properties",
        "update_custom_property",
        "archive_custom_property",
        "create_pipeline",
        "get_pipeline",
        "list_pipelines",
        "update_pipeline",
        "replace_pipeline",
        "delete_pipeline",
        # Pipelines resolve to the object's own scope — deals pipelines need
        # crm.objects.deals.*, ticket pipelines `tickets`, order pipelines
        # crm.pipelines.orders.* — so the object_type field decides.
        "create_pipeline_stage",
        "get_pipeline_stage",
        "list_pipeline_stages",
        "update_pipeline_stage",
        "replace_pipeline_stage",
        "delete_pipeline_stage",
        # MISSING SCOPE: crm.objects.leads.read / crm.objects.leads.write
        "create_lead",
        "get_lead",
        "list_leads",
        "search_leads",
        "update_lead",
        "delete_lead",
        # MISSING SCOPE: crm.objects.line_items.read / .write
        "create_line_item",
        "get_line_item",
        "list_line_items",
        "search_line_items",
        "update_line_item",
        "delete_line_item",
        # MISSING SCOPE: crm.objects.products.read / .write (the legacy
        # blanket equivalent is `e-commerce`).
        "create_product",
        "get_product",
        "list_products",
        "search_products",
        "update_product",
        "delete_product",
        # MISSING SCOPE: crm.objects.quotes.read / .write
        "create_quote",
        "get_quote",
        "list_quotes",
        "search_quotes",
        "update_quote",
        "delete_quote",
        # MISSING SCOPE: crm.objects.orders.read / .write
        "create_order",
        "get_order",
        "list_orders",
        "search_orders",
        "update_order",
        "delete_order",
        # MISSING SCOPE: crm.objects.owners.read
        "list_account_owners",
        # MISSING SCOPE: crm.objects.goals.read
        "get_goal",
        "list_goals",
        # MISSING SCOPE: crm.objects.feedback_submissions.read — HubSpot's
        # master scope table spells it singular (`feedback_submission`) and the
        # API guide plural; verify against the app's scope picker before adding.
        "get_feedback_submission",
        "list_feedback_submissions",
        # MISSING SCOPE: crm.objects.marketing_events.read / .write
        "create_marketing_event",
        "get_marketing_event",
        "list_marketing_events",
        "update_marketing_event",
        "delete_marketing_event",
        "create_event_attendance",
        "get_event_attendance",
        "delete_event_attendance",
        # MISSING SCOPE: marketing.campaigns.read / marketing.campaigns.write
        "create_marketing_campaign",
        "get_marketing_campaign",
        "list_marketing_campaigns",
        "update_marketing_campaign",
        "delete_marketing_campaign",
        "get_campaign_assets",
        "update_campaign_budget",
        # MISSING SCOPE: crm.schemas.custom.read / crm.schemas.custom.write
        "create_custom_object_schema",
        "get_custom_object_schema",
        "list_custom_object_schemas",
        "update_custom_object_schema",
        "delete_custom_object_schema",
        "purge_custom_object_schema",
        # MISSING SCOPE: crm.lists.read / crm.lists.write
        "create_contact_list",
        "get_contact_list",
        "list_contact_lists",
        "update_contact_list",
        "delete_contact_list",
        "add_contacts_to_list_batch",
        # MISSING SCOPE: communication_preferences.read /
        # communication_preferences.write — email subscription types, not lists.
        "get_contact_subscription_status",
        "list_subscription_types",
        "subscribe_contact_to_list",
        "unsubscribe_contact_from_list",
        # MISSING SCOPE: crm.import / crm.export
        "create_data_import",
        "get_import_status",
        "create_data_export",
        "get_export_status",
        "download_data_export",
        # MISSING SCOPE: files
        "upload_file",
        "get_file",
        "list_files",
        "update_file",
        "delete_file",
        # MISSING SCOPE: hubdb
        "create_hubdb_table",
        "get_hubdb_table",
        "list_hubdb_tables",
        "update_hubdb_table",
        "delete_hubdb_table",
        "clone_hubdb_table",
        "publish_hubdb_table",
        "create_hubdb_row",
        "get_hubdb_row",
        "list_hubdb_rows",
        "update_hubdb_row",
        "delete_hubdb_row",
        # MISSING SCOPE: content — CMS pages, blog posts/authors/topics, URL
        # redirects and the site-search settings + content search endpoints.
        "create_website_page",
        "get_website_page",
        "list_website_pages",
        "update_website_page",
        "delete_website_page",
        "publish_website_page",
        "create_blog_post",
        "get_blog_post",
        "list_blog_posts",
        "update_blog_post",
        "delete_blog_post",
        "create_blog_author",
        "get_blog_author",
        "list_blog_authors",
        "get_blog_topic",
        "list_blog_topics",
        "create_url_redirect",
        "get_url_redirect",
        "list_url_redirects",
        "update_url_redirect",
        "delete_url_redirect",
        "get_search_settings",
        "search_website_content",
        # MISSING SCOPE: cms.domains.read
        "get_domain",
        "list_domains",
        # MISSING SCOPE: automation — workflows and their enrollments.
        "get_workflow",
        "list_workflows",
        "enroll_contact_in_workflow",
        "unenroll_contact_from_workflow",
        # MISSING SCOPE: automation.sequences.read (reads) and
        # automation.sequences.enrollments.write (enroll/unenroll).
        "get_sequence",
        "list_sequences",
        "enroll_contact_in_sequence",
        "unenroll_contact_from_sequence",
        # MISSING SCOPE: conversations.read / conversations.write
        "get_conversation_thread",
        "list_conversation_threads",
        "list_conversation_messages",
        "send_conversation_message",
        "update_conversation_status",
        "create_communication_channel",
        "get_communication_channel",
        "list_communication_channels",
        # MISSING SCOPE: conversations.visitor_identification.tokens.create
        "identify_website_visitor",
        "get_visitor",
        # MISSING SCOPE: behavioral_events.event_definitions.read_write
        # (definitions) and analytics.behavioral_events.send (send_custom_event).
        "create_custom_event_definition",
        "list_custom_event_definitions",
        "update_custom_event_definition",
        "send_custom_event",
        # MISSING SCOPE: settings.users.read / settings.users.write — user
        # provisioning; roles are read under settings.users.read.
        "create_user",
        "get_user",
        "list_users",
        "update_user",
        "delete_user",
        "get_role",
        "list_roles",
        # MISSING SCOPE: settings.users.teams.read
        "get_team",
        "list_teams",
        # MISSING SCOPE: account-info.security.read
        "list_audit_logs",
        # MISSING SCOPE: business_units_view.read — HubSpot's master scope
        # table spells it `business_units.view.read`; the API guide uses the
        # underscore form. Verify in the app's scope picker before adding.
        "get_business_unit",
        "list_business_units",
        # MISSING SCOPE: social — one combined scope for the Broadcast API
        # (/social/v1/...); there is no read/write split.
        "create_social_post",
        "get_social_post",
        "list_social_posts",
        "schedule_social_post",
        "delete_social_post",
        "list_social_media_channels",
    ),
)
