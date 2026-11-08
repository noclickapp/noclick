"""Native service-token family; actual Humanitec RBAC stays authoritative."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

OPERATIONS = ("test_connection", "get_organization", "list_applications", "get_application", "list_environment_types", "list_environments", "get_environment", "list_deployments", "get_deployment", "list_pipelines", "get_pipeline", "list_pipeline_runs", "get_pipeline_run", "create_application", "rename_application", "rename_environment")
HUMANITEC_SCOPES = ScopeRegistry("humanitec", {
    operation: ScopeRequirement(credential_types=("humanitec_service_token",), note="Actual current saved service-user token, selected organization/resource RBAC and metadata-write policy required. No invented OAuth scope, actor or entitlement.")
    for operation in OPERATIONS
})
