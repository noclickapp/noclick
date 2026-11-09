"""Netlify OAuth uses account authorization without named scopes.

https://docs.netlify.com/api-and-cli-guides/api-guides/get-started-with-api/#authentication
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.netlify_operations import CATALOG

NETLIFY_SCOPES = ScopeRegistry(
    provider="netlify",
    requirements={name: ScopeRequirement() for name in
                  [op["name"] for op in CATALOG["operations"]] + ["test_connection", "on_deploy_succeeded", "on_deploy_failed", "on_deploy_started", "on_form_submission"]},
    enforcement=Enforcement.STRICT,
)
