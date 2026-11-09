"""Scope requirements from the pinned ServiceTitan CRM v2 contract (version 1.0)."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

SERVICETITAN_SCOPES = ScopeRegistry("servicetitan", {
    'on_new_or_updated_customer': ScopeRequirement(('tn.crm.customers:r',)),
    'on_new_or_updated_location': ScopeRequirement(('tn.crm.locations:r',)),
    'on_new_or_updated_lead': ScopeRequirement(('tn.crm.leads:r',)),
    'list_customers': ScopeRequirement(('tn.crm.customers:r',)),
    'get_customer': ScopeRequirement(('tn.crm.customers:r',)),
    'update_customer': ScopeRequirement(('tn.crm.customers:w',)),
    'list_customer_notes': ScopeRequirement(('tn.crm.customers:r',)),
    'create_customer_note': ScopeRequirement(('tn.crm.customers:w',)),
    'list_customer_contacts': ScopeRequirement(('tn.crm.customers:r',)),
    'list_locations': ScopeRequirement(('tn.crm.locations:r',)),
    'get_location': ScopeRequirement(('tn.crm.locations:r',)),
    'update_location': ScopeRequirement(('tn.crm.locations:w',)),
    'list_location_notes': ScopeRequirement(('tn.crm.locations:r',)),
    'create_location_note': ScopeRequirement(('tn.crm.locations:w',)),
    'list_location_contacts': ScopeRequirement(('tn.crm.locations:r',)),
    'list_leads': ScopeRequirement(('tn.crm.leads:r',)),
    'get_lead': ScopeRequirement(('tn.crm.leads:r',)),
    'update_lead': ScopeRequirement(('tn.crm.leads:w',)),
    'list_lead_notes': ScopeRequirement(('tn.crm.leads:r',)),
    'create_lead_note': ScopeRequirement(('tn.crm.leads:w',)),
    'create_lead_follow_up': ScopeRequirement(('tn.crm.leads:w',)),
    'dismiss_lead': ScopeRequirement(('tn.crm.leads:w',)),
})
