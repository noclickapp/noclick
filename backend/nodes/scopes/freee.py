"""Scopes: https://github.com/freee/freee-api-schema/blob/master/v2020_06_15/open-api-3/api-schema.json

The published root security requires both read and write for every operation.
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.freee_operations import FREEE_OPERATIONS, FREEE_TRIGGERS

FREEE_SCOPES = ScopeRegistry(provider="freee", requirements={
    name: ScopeRequirement(("read", "write")) for name in (*FREEE_OPERATIONS, *FREEE_TRIGGERS)
}, enforcement=Enforcement.STRICT)
