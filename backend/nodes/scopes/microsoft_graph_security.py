"""Delegated permissions: https://learn.microsoft.com/graph/permissions-reference."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
GRAPH_SECURITY_SCOPES = ScopeRegistry(provider="microsoft", requirements={
    'list_alerts': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityAlert.ReadWrite.All",)),
    'get_alert': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityAlert.ReadWrite.All",)),
    'update_alert': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityAlert.ReadWrite.All",)),
    'list_incidents': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityIncident.ReadWrite.All",)),
    'get_incident': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityIncident.ReadWrite.All",)),
    'update_incident': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityIncident.ReadWrite.All",)),
    'list_incident_alerts': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityIncident.ReadWrite.All",)),
    'list_secure_scores': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityEvents.Read.All",)),
    'get_secure_score': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityEvents.Read.All",)),
    'list_control_profiles': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityEvents.Read.All",)),
    'get_control_profile': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityEvents.Read.All",)),
    'on_updated_alert': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityAlert.ReadWrite.All",)),
    'on_updated_incident': ScopeRequirement(scopes=("https://graph.microsoft.com/SecurityIncident.ReadWrite.All",)),
}, extra_scopes={"default": ("https://graph.microsoft.com/User.Read", "offline_access")})
