"""Record/people providers (Attio, Apollo, BambooHR) → OAuth scope requirements.

Grouped because all three scope a token per record family × read/write over
people and company data — CRM records and lists, prospect/contact data, employee
records. Their published rigor differs enormously, and that difference is the
useful output here:

- **Attio** documents a required scope on every endpoint page.
- **BambooHR** documents scopes on every endpoint too, but only inside the
  OpenAPI block of each reference page; the lists are OR-alternatives.
- **Apollo** documents no per-endpoint scope anywhere, so nothing is mappable.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


# ---------------------------------------------------------------------------
# Attio — every endpoint page under
# https://docs.attio.com/rest-api/endpoint-reference/ carries a literal
# "Required scopes: ..." line; the table below is transcribed from them.
#
# Attio defines each family as a `:read` / `:read-write` pair, both described
# in its OAuth scope catalog as "View, and optionally write ..." — the
# read-write grant subsumes the read one. This node requests the read-write
# form for eight families, so `_a()` records a documented `:read` requirement
# at the level the token actually carries. Families held read-only
# (user_management, meeting, call_recording, file) keep their documented
# string, and any requirement outside the map is passed through untouched so
# an operation needing e.g. `file:read-write` still fails coverage.
# ---------------------------------------------------------------------------

_ATTIO_GRANTED = {
    "record_permission:read": "record_permission:read-write",
    "object_configuration:read": "object_configuration:read-write",
    "list_entry:read": "list_entry:read-write",
    "list_configuration:read": "list_configuration:read-write",
    "comment:read": "comment:read-write",
    "note:read": "note:read-write",
    "task:read": "task:read-write",
    "webhook:read": "webhook:read-write",
}


def _a(*scopes: str) -> ScopeRequirement:
    """Documented Attio scopes, raised to the grant level the node requests."""
    return ScopeRequirement(
        scopes=tuple(dict.fromkeys(_ATTIO_GRANTED.get(s, s) for s in scopes))
    )


# Attribute/select-option/status endpoints take a runtime `target` of objects
# OR lists and require the matching configuration family, so both are declared.
_ATTR_READ = ("object_configuration:read", "list_configuration:read")
_ATTR_WRITE = ("object_configuration:read-write", "list_configuration:read-write")

_ATTIO: dict[str, ScopeRequirement] = {
    # -- records ---------------------------------------------------------
    "list_records": _a("record_permission:read", "object_configuration:read"),
    "search_records": _a("record_permission:read", "object_configuration:read"),
    "get_record": _a("record_permission:read", "object_configuration:read"),
    "create_record": _a("record_permission:read-write", "object_configuration:read"),
    "update_record": _a("record_permission:read-write", "object_configuration:read"),
    "overwrite_record": _a("record_permission:read-write", "object_configuration:read"),
    "upsert_record": _a("record_permission:read-write", "object_configuration:read"),
    "delete_record": _a("record_permission:read-write", "object_configuration:read"),
    "list_record_attribute_values": _a(
        "record_permission:read", "object_configuration:read"
    ),
    "list_record_entries": _a(
        "record_permission:read", "object_configuration:read", "list_entry:read"
    ),
    # -- objects ---------------------------------------------------------
    "list_objects": _a("object_configuration:read"),
    "get_object": _a("object_configuration:read"),
    "create_object": _a("object_configuration:read-write"),
    "update_object": _a("object_configuration:read-write"),
    # -- attributes / select options / statuses --------------------------
    "list_attributes": _a(*_ATTR_READ),
    "get_attribute": _a(*_ATTR_READ),
    "create_attribute": _a(*_ATTR_WRITE),
    "update_attribute": _a(*_ATTR_WRITE),
    "list_select_options": _a(*_ATTR_READ),
    "create_select_option": _a(*_ATTR_WRITE),
    "update_select_option": _a(*_ATTR_WRITE),
    "list_statuses": _a(*_ATTR_READ),
    "create_status": _a(*_ATTR_WRITE),
    "update_status": _a(*_ATTR_WRITE),
    # -- lists -----------------------------------------------------------
    "list_lists": _a("list_configuration:read"),
    "get_list": _a("list_configuration:read"),
    "create_list": _a("list_configuration:read-write"),
    "update_list": _a("list_configuration:read-write"),
    # -- list entries ----------------------------------------------------
    "list_entries": _a("list_entry:read", "list_configuration:read"),
    "get_list_entry": _a("list_entry:read", "list_configuration:read"),
    "list_list_entry_attribute_values": _a(
        "list_entry:read", "list_configuration:read"
    ),
    "create_list_entry": _a("list_entry:read-write", "list_configuration:read"),
    "update_list_entry": _a("list_entry:read-write", "list_configuration:read"),
    "overwrite_list_entry": _a("list_entry:read-write", "list_configuration:read"),
    "assert_list_entry": _a("list_entry:read-write", "list_configuration:read"),
    "delete_list_entry": _a("list_entry:read-write", "list_configuration:read"),
    # -- notes -----------------------------------------------------------
    "list_notes": _a("note:read", "object_configuration:read", "record_permission:read"),
    "get_note": _a("note:read", "object_configuration:read", "record_permission:read"),
    "create_note": _a(
        "note:read-write", "object_configuration:read", "record_permission:read"
    ),
    "delete_note": _a("note:read-write"),
    # -- tasks -----------------------------------------------------------
    "list_tasks": _a(
        "task:read",
        "object_configuration:read",
        "record_permission:read",
        "user_management:read",
    ),
    "get_task": _a(
        "task:read",
        "object_configuration:read",
        "record_permission:read",
        "user_management:read",
    ),
    "create_task": _a(
        "task:read-write",
        "object_configuration:read",
        "record_permission:read",
        "user_management:read",
    ),
    "update_task": _a(
        "task:read-write",
        "object_configuration:read",
        "record_permission:read",
        "user_management:read",
    ),
    "delete_task": _a("task:read-write"),
    # -- comments and threads --------------------------------------------
    "create_comment": _a("comment:read-write"),
    "create_entry_comment": _a("comment:read-write"),
    "reply_to_thread": _a("comment:read-write"),
    "delete_comment": _a("comment:read-write"),
    "get_comment": _a("comment:read"),
    "list_threads": _a("comment:read"),
    "list_entry_threads": _a("comment:read"),
    "get_thread": _a("comment:read"),
    # -- workspace members -----------------------------------------------
    "list_workspace_members": _a("user_management:read"),
    "get_workspace_member": _a("user_management:read"),
    # GET /v2/self introspects the token itself and states no required scope.
    "identify_self": _a(),
    # -- files and meetings (read-only families) -------------------------
    "list_files": _a("file:read", "object_configuration:read", "record_permission:read"),
    "get_file": _a("file:read", "object_configuration:read", "record_permission:read"),
    "list_meetings": _a("meeting:read", "record_permission:read"),
    "get_meeting": _a("meeting:read", "record_permission:read"),
    # -- triggers: each creates a webhook subscription --------------------
    # Only the subscription create/delete is documented as scoped; Attio does
    # not state a resource read scope for receiving the delivered events.
    "on_attio_event": _a("webhook:read-write"),
    "on_record_event": _a("webhook:read-write"),
    "on_list_entry_event": _a("webhook:read-write"),
    "on_note_event": _a("webhook:read-write"),
    "on_task_event": _a("webhook:read-write"),
    "on_comment_event": _a("webhook:read-write"),
}

ATTIO_SCOPES = ScopeRegistry(provider="attio", requirements=_ATTIO)


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


# ---------------------------------------------------------------------------
# BambooHR — scopes are published in the `securitySchemes` block of every
# reference page under https://documentation.bamboohr.com/reference/... .
#
# Two semantics matter:
#  - The scope list on an endpoint is OR, not AND: any one of the listed
#    scopes authorizes the call. Each entry below names the alternative the
#    node already requests.
#  - On employee endpoints the base `employee` / `employee.write` authorizes
#    the CALL, while the `employee:<area>` and `sensitive_employee:<area>`
#    sub-scopes gate WHICH FIELDS come back. We request none of those, so
#    employee reads return a thin subset of fields rather than failing — a
#    silent partial, not a missing_scope.
# ---------------------------------------------------------------------------

_BAMBOOHR: dict[str, ScopeRequirement] = {
    # -- employees -------------------------------------------------------
    "get_employee": _s("employee"),
    "get_employee_directory": _s("employee_directory"),
    "add_employee": _s("employee.write"),
    "update_employee": _s("employee.write"),
    "get_employee_photo": _s("employee:photo"),
    # -- employee tables -------------------------------------------------
    "get_table_rows": _s("employee"),
    "get_changed_table_rows": _s("employee"),
    "add_table_row": _s("employee.write"),
    "update_table_row": _s("employee.write"),
    "delete_table_row": _s("employee.write"),
    # -- time off --------------------------------------------------------
    "list_time_off_requests": _s("time_off"),
    "estimate_future_balance": _s("time_off"),
    "list_time_off_types": _s("time_off"),
    "list_time_off_policies": _s("time_off"),
    "get_whos_out": _s("time_off"),
    "add_time_off_request": _s("time_off.write"),
    "change_time_off_request_status": _s("time_off.write"),
    "add_time_off_history": _s("time_off.write"),
    "adjust_time_off_balance": _s("time_off.write"),
    # -- reports / datasets ----------------------------------------------
    "list_datasets": _s("report"),
    "get_report": _s("report"),
    "request_custom_report": _s("report"),
    # -- files -----------------------------------------------------------
    "list_employee_files": _s("employee:file"),
    "get_employee_file": _s("employee:file"),
    "upload_employee_file": _s("employee:file.write"),
    "delete_employee_file": _s("employee:file.write"),
    "list_company_files": _s("company_file"),
    "get_company_file": _s("company_file"),
    # -- metadata --------------------------------------------------------
    # GET /meta/fields accepts `field` OR `employee`; the others take `field`
    # only, which we do not request (see unmapped).
    "list_fields": _s("employee"),
    "list_users": _s("user"),
    "get_account": _s("company:info"),
    # -- webhooks --------------------------------------------------------
    "list_webhooks": _s("webhooks"),
    "get_webhook": _s("webhooks"),
    "list_monitor_fields": _s("webhooks"),
    "create_webhook": _s("webhooks.write"),
    "update_webhook": _s("webhooks.write"),
    "delete_webhook": _s("webhooks.write"),
    # -- triggers (each registers a webhook subscription) ----------------
    "on_field_change": _s("webhooks.write"),
    "on_personal_info_change": _s("webhooks.write"),
    "on_contact_info_change": _s("webhooks.write"),
    "on_job_change": _s("webhooks.write"),
    "on_employment_status_change": _s("webhooks.write"),
}

BAMBOOHR_SCOPES = ScopeRegistry(
    provider="bamboohr",
    requirements=_BAMBOOHR,
    unmapped=(
        # MISSING SCOPE: public.integration OR public.user. GET
        # /employees/changed lists only those two alternatives, and both are
        # actor-type scopes we never request.
        "get_changed_employees",
        # MISSING SCOPE: field. GET /meta/tables and GET /meta/lists accept
        # `field` only — our `meta` scope covers the country/state/timezone
        # lookup endpoints, not these.
        "list_tabular_fields",
        "get_lists",
        # These call paths are absent from BambooHR's published spec (the real
        # surface is /time_tracking/... and /timetracking/...), so there is no
        # endpoint page to read a scope off. `time_tracking(.write)` is
        # requested and is the obvious family, but the endpoints as called
        # look wrong independently of scopes.
        "get_timesheet_summary",
        "clock_in",
        "clock_out",
        "add_time_tracking",
        "update_time_tracking",
        "delete_time_tracking",
    ),
)
