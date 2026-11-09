"""Permissions published in Kiwify public API 1.0.0 operation security objects.

https://docs.kiwify.com.br/api-reference/openapi.json
The token is pasted, so permissions must be selected in Kiwify when creating
its API key. This registry records what each operation actually needs.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.kiwify_operations import KIWIFY_OPERATIONS

KIWIFY_SCOPES = ScopeRegistry(
    provider="kiwify",
    requirements={
        operation: ScopeRequirement(scopes=(spec["scope"],))
        for operation, spec in KIWIFY_OPERATIONS.items()
    },
)
