"""Yelp Leads scope: https://docs.developer.yelp.com/docs/authorization-code-workflow."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

YELP_LEADS_SCOPES = ScopeRegistry(
    provider="yelp_leads",
    requirements={name: ScopeRequirement(scopes=("leads",)) for name in (
        "get_lead", "get_lead_events", "get_older_lead_events", "get_newer_lead_events",
        "mark_lead_replied_by_phone", "mark_lead_replied_by_email", "write_lead_event", "mark_lead_as_replied",
        "mark_lead_event_as_read", "list_lead_ids",
    )},
)
