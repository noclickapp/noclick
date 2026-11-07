"""Closed Mighty API operations; alternative scopes are not conjunctions."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

TYPES = ("mighty_networks_api_key", "mighty_networks_supplied_oauth")
MUTATION_SCOPES = {
    "create_private_space": ("host:write:network_spaces",),
    "rename_space": ("host:write:network_spaces",),
    "create_collection": ("host:write:network_spaces",),
    "rename_collection": ("host:write:network_spaces",),
    "delete_empty_collection": ("host:write:network_spaces",),
    "create_tag": ("host:write:network_members",),
    "update_tag": ("host:write:network_members",),
    "delete_tag": ("host:write:network_members",),
    "create_draft_post": ("write:posts", "host:write:network_posts"),
    "update_draft_post": ("write:posts", "host:write:network_posts"),
    "delete_draft_post": ("write:posts", "host:write:network_posts"),
}
READS = ("test_connection", "get_me", "get_network", "list_spaces", "get_space",
         "list_space_templates", "list_collections", "get_collection", "list_tags",
         "get_tag", "list_posts", "get_post")
MIGHTY_NETWORKS_SCOPES = ScopeRegistry("mighty_networks", {
    operation: ScopeRequirement(credential_types=TYPES, note=(
        "Required mutation scope, any one: " + ", ".join(MUTATION_SCOPES[operation])
        if operation in MUTATION_SCOPES else
        "Mighty enforces the token's actual approved scopes and the user's visibility. "
        "Read scope/plan coverage is not inferred from a successful me/network probe."
    )) for operation in (*READS, *MUTATION_SCOPES)
})
