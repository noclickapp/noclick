"""Canva → OAuth scope requirements (the family's shared notes are in content_storage.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.scopes.content_storage import _s


# ---------------------------------------------------------------------------
# Canva — https://www.canva.dev/docs/connect/appendix/scopes/
#
# Verified against the published Connect OpenAPI spec
# (https://www.canva.dev/sources/connect/api/latest/api.yml) with the per-
# endpoint reference pages spot-checked. Canva scopes are explicitly NOT
# hierarchical — `asset:write` does not imply `asset:read` — so read and write
# halves are declared separately wherever both are used.
# ---------------------------------------------------------------------------

_CANVA: dict[str, ScopeRequirement] = {
    # -- designs ---------------------------------------------------------
    "list_user_designs": _s("design:meta:read"),
    "get_design_metadata": _s("design:meta:read"),
    "create_design": _s("design:content:write"),
    "list_design_pages": _s("design:content:read"),
    "get_design_export_formats": _s("design:content:read"),
    "create_design_export_job": _s("design:content:read"),
    "get_design_export_job_status": _s("design:content:read"),
    "import_design_from_url": _s("design:content:write"),
    "get_design_import_job_status": _s("design:content:write"),
    "import_design_from_binary_file": _s("design:content:write"),
    "get_binary_design_import_job_status": _s("design:content:write"),
    # Resize additionally needs the account's `resize` capability; scopes alone
    # do not unlock it (check via get_user_available_features).
    "create_design_resize_job": _s("design:content:read", "design:content:write"),
    "get_design_resize_job_status": _s("design:content:read", "design:content:write"),
    # -- assets ----------------------------------------------------------
    "upload_asset_from_url": _s("asset:write"),
    "upload_asset_from_binary": _s("asset:write"),
    "get_asset_upload_job_status": _s("asset:read"),
    "get_binary_asset_upload_job_status": _s("asset:read"),
    "get_asset_metadata": _s("asset:read"),
    "update_asset_name_or_tags": _s("asset:write"),
    "delete_asset": _s("asset:write"),
    # -- folders ---------------------------------------------------------
    "create_folder": _s("folder:write"),
    "get_folder_details": _s("folder:read"),
    "update_folder_name": _s("folder:write"),
    "delete_folder": _s("folder:write"),
    "list_folder_contents": _s("folder:read"),
    "move_item_to_folder": _s("folder:write"),
    # -- brand templates + autofill --------------------------------------
    "list_brand_templates_with_search": _s("brandtemplate:meta:read"),
    "get_brand_template_metadata": _s("brandtemplate:meta:read"),
    "get_autofill_dataset_definition": _s("brandtemplate:content:read"),
    "create_design_autofill_job": _s("design:content:write"),
    "get_design_autofill_job_status": _s("design:meta:read"),
    # -- comments --------------------------------------------------------
    "create_design_comment_thread": _s("comment:write"),
    "create_comment_thread_reply": _s("comment:write"),
    "get_design_comment_thread": _s("comment:read"),
    "list_comment_thread_replies": _s("comment:read"),
    "get_comment_thread_reply": _s("comment:read"),
    # -- user ------------------------------------------------------------
    # /v1/users/me needs a valid token but no scope — the safe connectivity probe.
    "get_current_user_id": _s(),
    "get_user_profile_information": _s("profile:read"),
    "get_user_available_features": _s("profile:read"),
    # -- token/key endpoints: client credentials or unauthenticated ------
    "verify_token_validity": _s(),
    "revoke_access_or_refresh_token": _s(),
    "get_webhook_signature_verification_keys": _s(),
    "get_openid_connect_jwks": _s(),
    "get_app_json_web_key_set": _s(),
}

CANVA_SCOPES = ScopeRegistry(
    provider="canva",
    requirements=_CANVA,
    unmapped=(
        # MISSING SCOPE: openid + profile (and/or email). GET /v1/oidc/userinfo
        # is an OIDC endpoint; the OIDC `profile` scope is a DIFFERENT scope
        # from the `profile:read` we request, so this operation 403s today.
        "fetch_current_user_oidc_claims",
    ),
)
