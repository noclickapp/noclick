"""Apollo → OAuth scope requirements (the family's shared notes are in crm_records.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry


# ---------------------------------------------------------------------------
# Apollo — https://docs.apollo.io/docs/use-oauth-20-authorization-flow-to-access-apollo-user-information-partners
#
# Apollo's OAuth page names a handful of scope strings in example URLs and
# asserts that "each scope provides access to specific Apollo API endpoints",
# but publishes no mapping — and its own OpenAPI document
# (https://docs.apollo.io/openapi/apollo-rest-api.json) declares only apiKey
# and http-bearer security schemes, so not one of its operations can carry a
# scope. Nothing here is derivable from the docs; the table would be pure
# guesswork, so every operation is declared unmapped instead.
#
# What Apollo DOES document per endpoint is a master-API-key requirement: the
# call-record, email-account and several bulk endpoints return
# 403 API_INACCESSIBLE without one. That is an access gate, not a scope.
# ---------------------------------------------------------------------------

APOLLO_SCOPES = ScopeRegistry(
    provider="apollo",
    requirements={},
    unmapped=(
        "enrich_single_person",
        "enrich_multiple_people",
        "enrich_single_organization",
        "enrich_multiple_organizations",
        "search_people_in_apollo",
        "search_organizations_in_apollo",
        "get_organization_job_postings",
        "get_organization_details",
        "search_organization_news_articles",
        "create_account",
        "update_account_details",
        "search_accounts",
        "get_account_details",
        "list_account_stages",
        "create_multiple_accounts",
        "update_multiple_accounts",
        "update_account_stage_bulk",
        "update_account_ownership",
        "create_contact",
        "update_contact_details",
        "search_contacts",
        "get_contact_details",
        "list_contact_stages",
        "create_multiple_contacts",
        "update_multiple_contacts",
        "update_contact_stage_bulk",
        "update_contact_ownership",
        "create_deal",
        "list_deals",
        "get_deal_details",
        "update_deal_details",
        "list_deal_stages",
        "search_outreach_sequences",
        "add_contacts_to_outreach_sequence",
        "update_contact_sequence_status",
        "search_sequence_emails",
        "get_sequence_email_statistics",
        "create_task",
        "search_tasks",
        "create_call_activity_record",
        "search_call_records",
        "update_call_record",
        "get_organization_users",
        "get_email_account_list",
        "get_api_usage_and_limits",
        "get_organization_lists",
        "get_organization_custom_fields",
        "create_custom_field",
    ),
)
