"""Reddit Ads OAuth requirements from the official v3 OpenAPI security entries.

Ads reads and reporting require adsread; campaign, ad-group and ad writes require
adsedit. Reuses staging's Reddit consent flow rather than registering another app.
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.reddit_ads_operations import OPERATIONS

REDDIT_ADS_SCOPES = ScopeRegistry(
    provider="reddit", enforcement=Enforcement.STRICT,
    requirements={
        operation: ScopeRequirement(scopes=("adsedit" if operation.startswith(("create_", "update_")) else "adsread",))
        for operation in OPERATIONS
    },
)
