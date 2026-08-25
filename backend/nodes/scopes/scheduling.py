"""Scheduling providers (Calendly, Cal.com, Fathom) → OAuth scope requirements.

Grouped because all three scope a token over the same small vocabulary —
bookings, availability, meeting records — and because all three are, for
different reasons, mostly unmappable today:

- **Calendly** shipped a granular scope catalog in 2026, but our app requests
  NONE of it, so every operation is a missing-scope report rather than a
  requirement (see ``CALENDLY_SCOPES``).
- **Cal.com** publishes a permission enum for Platform OAuth clients and never
  says which endpoint needs which permission.
- **Fathom** mints one coarse ``public_api`` scope covering the whole API, so
  every operation maps to it and there is nothing finer to declare.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


# ---------------------------------------------------------------------------
# Calendly — https://developer.calendly.com/scopes
#
# Calendly introduced scoped permissions in 2026. Legacy OAuth apps and PATs
# issued before that keep full access, which is the ONLY reason this node works
# today: `get_calendly_auth_url` sends no `scope` parameter at all (the
# credential's `x-oauth-scopes` is `[]`), so a freshly created Calendly app
# would be granted nothing.
#
# Every operation therefore needs a scope the app never requests. Per the
# migration rules those are reported, not silently added — adding them forces
# a re-auth for every connected user and is a batched decision.
#
# The documented mapping, so the batch decision is a lookup and not a re-research:
#   users:read              get_current_user, get_user
#   event_types:read        list_event_types, get_event_type,
#                           list_event_type_available_times
#   scheduled_events:read   list_scheduled_events, get_scheduled_event,
#                           list_event_invitees, get_event_invitee, get_no_show
#   scheduled_events:write  cancel_scheduled_event, create_no_show, delete_no_show
#   organizations:read      get_organization, list_organization_memberships,
#                           get_organization_membership,
#                           list_organization_invitations
#   organizations:write     remove_organization_membership,
#                           create_organization_invitation,
#                           revoke_organization_invitation
#   scheduling_links:write  create_scheduling_link
#   shares:write            create_share
#   availability:read       list_user_availability_schedules, list_user_busy_times
#   routing_forms:read      list_routing_forms, list_routing_form_submissions
#   groups:read             list_groups, list_group_relationships
#   activity_log:read       list_activity_log
#   data_compliance:write   delete_invitee_data, delete_event_data
#   webhooks:write          all on_* triggers (webhook subscription create/delete)
#   contacts:read/write     on_contact_* triggers
# ---------------------------------------------------------------------------

CALENDLY_SCOPES = ScopeRegistry(
    provider="calendly",
    requirements={},
    unmapped=(
        # MISSING SCOPE: users:read
        "get_current_user",
        "get_user",
        # MISSING SCOPE: event_types:read
        "list_event_types",
        "get_event_type",
        "list_event_type_available_times",
        # MISSING SCOPE: scheduled_events:read
        "list_scheduled_events",
        "get_scheduled_event",
        "list_event_invitees",
        "get_event_invitee",
        "get_no_show",
        # MISSING SCOPE: scheduled_events:write
        "cancel_scheduled_event",
        "create_no_show",
        "delete_no_show",
        # MISSING SCOPE: organizations:read
        "get_organization",
        "list_organization_memberships",
        "get_organization_membership",
        "list_organization_invitations",
        # MISSING SCOPE: organizations:write
        "remove_organization_membership",
        "create_organization_invitation",
        "revoke_organization_invitation",
        # MISSING SCOPE: scheduling_links:write / shares:write
        "create_scheduling_link",
        "create_share",
        # MISSING SCOPE: availability:read
        "list_user_availability_schedules",
        "list_user_busy_times",
        # MISSING SCOPE: routing_forms:read
        "list_routing_forms",
        "list_routing_form_submissions",
        # MISSING SCOPE: groups:read
        "list_groups",
        "list_group_relationships",
        # MISSING SCOPE: activity_log:read
        "list_activity_log",
        # MISSING SCOPE: data_compliance:write
        "delete_invitee_data",
        "delete_event_data",
        # MISSING SCOPE: webhooks:write (subscription create/delete), plus the
        # read scope of the resource each subscription carries.
        "on_invitee_created",
        "on_invitee_canceled",
        "on_invitee_no_show_created",
        "on_invitee_no_show_deleted",
        "on_routing_form_submission_created",
        # MISSING SCOPE: webhooks:write + contacts:read
        "on_contact_created",
        "on_contact_updated",
        "on_contact_deleted",
        # Caller supplies an arbitrary API path, so no fixed requirement exists.
        "custom_request",
    ),
)


# ---------------------------------------------------------------------------
# Cal.com — https://cal.com/docs/api-reference/v2/oauth-clients/create-an-oauth-client
#
# Cal.com publishes its permission vocabulary ONLY as the enum accepted by the
# OAuth-client management endpoint, and states nowhere which endpoint requires
# which permission. Nothing here is therefore mappable from the docs.
#
# Two facts the requested list gets wrong, reported rather than fixed:
#  - WEBHOOK_READ / WEBHOOK_WRITE are not members of the enum
#    (EVENT_TYPE_*, BOOKING_*, SCHEDULE_*, APPS_*, PROFILE_* and `*` are), so
#    sending them is rejected at client creation.
#  - The permissions apply only to Platform OAuth-client managed-user tokens;
#    for the API-key credential this node also accepts they are inert.
# ---------------------------------------------------------------------------

CAL_COM_SCOPES = ScopeRegistry(
    provider="cal_com",
    requirements={},
    unmapped=(
        # Bookings — inferred family BOOKING_READ / BOOKING_WRITE, undocumented.
        "list_bookings",
        "get_booking",
        "create_booking",
        "cancel_booking",
        "reschedule_booking",
        "confirm_booking",
        "decline_booking",
        "mark_no_show",
        "get_recordings",
        # Event types — inferred family EVENT_TYPE_READ / EVENT_TYPE_WRITE.
        "list_event_types",
        "get_event_type",
        "create_event_type",
        "update_event_type",
        "delete_event_type",
        # Schedules / out-of-office — inferred family SCHEDULE_READ / _WRITE.
        "list_schedules",
        "get_schedule",
        "create_schedule",
        "update_schedule",
        "delete_schedule",
        "list_ooo",
        "create_ooo",
        "delete_ooo",
        # Profile — inferred PROFILE_READ / PROFILE_WRITE.
        "get_me",
        "update_me",
        # Slots are served without an authenticated permission check.
        "get_slots",
        "reserve_slot",
        # MISSING SCOPE: none exists — Cal.com has no webhook permission.
        "list_webhooks",
        "on_booking_event",
    ),
)


# ---------------------------------------------------------------------------
# Fathom — https://developers.fathom.ai/sdks/oauth.md
#
# One scope for the whole API: `public_api` ("Access to the Fathom API").
# There is no per-endpoint scope surface, so every operation declares it.
# ---------------------------------------------------------------------------

_FATHOM_API = _s("public_api")

FATHOM_SCOPES = ScopeRegistry(
    provider="fathom",
    requirements={
        "list_meetings": _FATHOM_API,
        "list_meetings_with_summaries": _FATHOM_API,
        "list_meetings_with_action_items": _FATHOM_API,
        "list_meetings_with_crm_matches": _FATHOM_API,
        "list_meetings_by_type": _FATHOM_API,
        "list_external_meetings": _FATHOM_API,
        "list_meeting_types": _FATHOM_API,
        "get_summary": _FATHOM_API,
        "get_transcript": _FATHOM_API,
        "list_teams": _FATHOM_API,
        "list_team_members": _FATHOM_API,
        "create_webhook": _FATHOM_API,
        "delete_webhook": _FATHOM_API,
        "on_new_meeting": _FATHOM_API,
    },
)
