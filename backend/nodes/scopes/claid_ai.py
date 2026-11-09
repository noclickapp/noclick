"""Claid API-key permissions from https://api.claid.ai/docs-v1.json (v1).

These are key capabilities chosen in the Claid dashboard, not an OAuth flow.
See https://docs.claid.ai/authentication.md for key permission assignment.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

CLAID_AI_SCOPES = ScopeRegistry("claid-ai", {
    'list_storage_types': ScopeRequirement(('storage',)),
    'list_storages': ScopeRequirement(('storage',)),
    'create_storage': ScopeRequirement(('storage',)),
    'get_storage': ScopeRequirement(('storage',)),
    'delete_storage': ScopeRequirement(('storage',)),
    'update_storage': ScopeRequirement(('storage',)),
    'edit_image': ScopeRequirement(()),
    'edit_images_batch': ScopeRequirement(()),
    'get_batch_result': ScopeRequirement(('image_editing',)),
    'edit_image_async': ScopeRequirement(()),
    'get_edit_result': ScopeRequirement(('image_editing',)),
    'generate_images': ScopeRequirement(()),
    'create_scene': ScopeRequirement(()),
    'ai_edit_image': ScopeRequirement(()),
    'get_ai_edit_result': ScopeRequirement(('image_editing',)),
    'create_fashion_models': ScopeRequirement(()),
    'get_fashion_models_result': ScopeRequirement(('image_editing',)),
    'generate_video': ScopeRequirement(()),
    'get_video_result': ScopeRequirement(('video_generation',)),
})
