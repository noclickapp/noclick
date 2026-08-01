"""Per-provider OAuth scope requirement tables.

Each module declares a :class:`~nodes.core.oauth_scopes.ScopeRegistry` mapping
a node's API endpoints (or operation names) to the scopes they require. The
node's requested ``x-oauth-scopes`` is derived from that table rather than
hand-written, and ``tests/test_oauth_scope_coverage.py`` enforces coverage.
"""
