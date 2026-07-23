"""Supabase operation → OAuth scope requirements.

Supabase's OAuth scopes gate the **Management API only** ("Scopes restrict
access to the specific Supabase Management API endpoints for OAuth tokens").
Every one of this node's operations runs against the *project data plane*
instead — PostgREST (``/rest/v1``), GoTrue (``/auth/v1``), Storage
(``/storage/v1``), Realtime, Edge Functions — authenticated with the project's
``anon`` / ``service_role`` API key, never with the Management API access
token (see ``SupabaseNode._get_api_key``). Data-plane authorization is RLS and
the key's role, not an OAuth scope, so no operation carries a scope
requirement.

The scopes the node does need are consumed at CONNECT time, by the OAuth
handler rather than by any operation:

- ``secrets:read`` — "Retrieve a project's API keys", i.e.
  ``GET /v1/projects/{ref}/api-keys``, which caches the anon/service_role keys
  onto the credential.
- ``projects:read`` — "Retrieve a project's metadata", i.e. ``GET /v1/projects``
  to list the projects the user can connect.

Both are ``extra_scopes``: required, but implied by no endpoint the node calls.

Note also that Supabase's authorize URL carries no ``scope`` parameter — scopes
are configured on the OAuth app in the Supabase dashboard, so the node's
``x-oauth-scopes`` is documentation of the app's configuration rather than a
per-authorization request.

Docs: https://supabase.com/docs/guides/integrations/build-a-supabase-oauth-integration/oauth-scopes
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: Data-plane call: authorized by the project API key, gated by no OAuth scope.
_DATA_PLANE = ScopeRequirement()

_OPERATIONS = (
    # Table (PostgREST)
    "select_table_rows",
    "insert_table_rows",
    "update_table_rows",
    "upsert_table_rows",
    "delete_table_rows",
    "call_database_function",
    # Auth (GoTrue)
    "sign_up_user",
    "sign_in_with_password",
    "send_magic_link_signin",
    "sign_out_user",
    "get_current_user",
    "update_current_user",
    "send_password_reset_email",
    "verify_otp_code",
    "refresh_access_token",
    "admin_list_users",
    "admin_create_user",
    "admin_update_user",
    "admin_delete_user",
    # Storage
    "create_storage_bucket",
    "list_storage_buckets",
    "get_storage_bucket",
    "delete_storage_bucket",
    "empty_storage_bucket",
    "upload_storage_file",
    "download_storage_file",
    "list_bucket_files",
    "delete_storage_file",
    "move_storage_file",
    "copy_storage_file",
    "create_file_signed_url",
    "get_file_public_url",
    # Realtime + Edge Functions
    "broadcast_realtime_message",
    "invoke_edge_function",
)

_REQUIREMENTS = {operation: _DATA_PLANE for operation in _OPERATIONS}

SUPABASE_SCOPES = ScopeRegistry(
    provider="supabase",
    requirements=_REQUIREMENTS,
    # Consumed by the OAuth connect flow, not by any operation.
    extra_scopes={"default": ("secrets:read", "projects:read")},
)
