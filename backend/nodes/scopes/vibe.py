"""Scopes from each operation's x-scopes in Vibe's 2026-06-01 OpenAPI.

https://cdn.apps.vibe.co/open-api/public-api/2026-06-01/latest.yaml
Use literal endpoint scopes (account:read singular), not the incomplete global
security-scheme scope list. OAuth identity reads the same accounts endpoint.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement, Enforcement

VIBE_SCOPES = ScopeRegistry(provider="vibe", enforcement=Enforcement.STRICT, requirements={
    'list_accounts': ScopeRequirement(('account:read',)),
    'list_advertisers': ScopeRequirement(('advertisers:read',)),
    'create_advertiser': ScopeRequirement(('advertisers:write',)),
    'get_advertiser': ScopeRequirement(('advertisers:read',)),
    'update_advertiser': ScopeRequirement(('advertisers:write',)),
    'list_audiences': ScopeRequirement(('audiences:read',)),
    'get_audience': ScopeRequirement(('audiences:read',)),
    'create_audience': ScopeRequirement(('audiences:write',)),
    'list_campaigns': ScopeRequirement(('campaigns:read',)),
    'create_campaign': ScopeRequirement(('campaigns:write',)),
    'get_campaign': ScopeRequirement(('campaigns:read',)),
    'update_campaign': ScopeRequirement(('campaigns:write',)),
    'delete_campaign': ScopeRequirement(('campaigns:write',)),
    'perform_campaign_action': ScopeRequirement(('campaigns:write',)),
    'publish_campaign': ScopeRequirement(('campaigns:publish',)),
    'list_creatives': ScopeRequirement(('creatives:read',)),
    'list_strategies': ScopeRequirement(('campaigns:read',)),
    'create_strategy': ScopeRequirement(('campaigns:write',)),
    'get_strategy': ScopeRequirement(('campaigns:read',)),
    'update_strategy': ScopeRequirement(('campaigns:write',)),
    'delete_strategy': ScopeRequirement(('campaigns:write',)),
    'replace_strategy_creatives': ScopeRequirement(('campaigns:write',)),
    'perform_strategy_action': ScopeRequirement(('campaigns:write',)),
    'create_report': ScopeRequirement(('reporting:read',)),
    'get_report': ScopeRequirement(('reporting:read',)),
})
