"""Omnisend OAuth scopes from each operation's official API security declaration.

https://api-docs.omnisend.com/reference/oauth
https://api-docs.omnisend.com/reference/get_brands-current
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.omnisend_operations import CATALOG

OMNISEND_SCOPES = ScopeRegistry(
    "omnisend",
    {
        op["name"]: ScopeRequirement(
            op["scopes"],
            credential_types=("omnisend_oauth",) if op["name"] == "post_brands_current" else (),
            note="Connect brand requires an Omnisend OAuth account.",
        )
        for op in CATALOG["operations"]
    },
)
