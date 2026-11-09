"""Figma REST API scopes for the operations exposed by the workflow node.

https://developers.figma.com/docs/rest-api/scopes/
"""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


FIGMA_OPERATION_SCOPES = {
    "on_event": "webhooks:write",
    "get_current_user": "current_user:read",
    "get_file": "file_content:read",
    "get_file_nodes": "file_content:read",
    "render_images": "file_content:read",
    "get_image_fills": "file_content:read",
    "get_file_metadata": "file_metadata:read",
    "list_versions": "file_versions:read",
    "list_comments": "file_comments:read",
    "create_comment": "file_comments:write",
    "delete_comment": "file_comments:write",
    "list_reactions": "file_comments:read",
    "add_reaction": "file_comments:write",
    "delete_reaction": "file_comments:write",
    "list_file_components": "library_content:read",
    "list_file_component_sets": "library_content:read",
    "list_file_styles": "library_content:read",
    "list_dev_resources": "file_dev_resources:read",
    "create_dev_resource": "file_dev_resources:write",
    "update_dev_resource": "file_dev_resources:write",
    "delete_dev_resource": "file_dev_resources:write",
    "list_webhooks": "webhooks:read",
    "get_webhook": "webhooks:read",
    "create_webhook": "webhooks:write",
    "update_webhook": "webhooks:write",
    "delete_webhook": "webhooks:write",
}

FIGMA_SCOPES = ScopeRegistry(
    provider="figma",
    requirements={name: ScopeRequirement(scopes=(scope,)) for name, scope in FIGMA_OPERATION_SCOPES.items()},
)
