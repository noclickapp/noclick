"""Published Runscope v1.0.0 security requirements (personal bearer tokens).
https://github.com/Runscope/runscope-api-examples/blob/master/schemas/runscope-swagger-v2.json
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

RUNSCOPE_SCOPES = ScopeRegistry(provider="runscope", requirements={
    "get_account": ScopeRequirement(scopes=("api:read", "account:email")),
    "list_team_people": ScopeRequirement(scopes=("api:read", "account:email", "team:read")),
    "list_team_integrations": ScopeRequirement(scopes=("api:read", "team:read")),
    "list_team_agents": ScopeRequirement(scopes=("api:read", "team:read")),
    "list_buckets": ScopeRequirement(scopes=("api:read",)),
    "get_bucket": ScopeRequirement(scopes=("api:read",)),
    "create_bucket": ScopeRequirement(scopes=("api:read", "bucket:write")),
    "delete_bucket": ScopeRequirement(scopes=("api:read", "bucket:write")),
    **{name: ScopeRequirement(scopes=("api:read", "test:read")) for name in (
        "list_tests", "get_test", "list_steps", "list_test_environments", "list_shared_environments", "get_test_metrics")},
    **{name: ScopeRequirement(scopes=("api:read", "test:write")) for name in (
        "create_test", "update_test", "delete_test", "create_step", "update_step", "delete_step",
        "create_test_environment", "update_test_environment", "create_shared_environment", "update_shared_environment")},
    "on_test_completed": ScopeRequirement(scopes=("api:read", "test:read", "test:write")),
})
