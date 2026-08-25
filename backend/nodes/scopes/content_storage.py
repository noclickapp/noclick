"""Content/storage providers → OAuth scope requirements.

Grouped because Canva, Typeform, Dropbox and Box all scope a token by
*resource family × read/write* over user content — designs and assets, forms
and responses, files and folders. The strings differ in punctuation
(``asset:write``, ``forms:write``, ``files.content.write``, ``root_readwrite``)
but the shape, and therefore the reviewing work, is the same.

All four run at ``Enforcement.SUBSET``: the tables below cover only what the
providers publish, and several operations sit in ``unmapped`` because the
provider documents no scope for them at all.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


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


# ---------------------------------------------------------------------------
# Typeform — https://www.typeform.com/developers/get-started/scopes/
#
# That page is the ONLY place Typeform states scopes; the per-endpoint
# reference pages carry none. It covers the forms/themes/images/workspaces/
# responses/webhooks families and nothing else, so the translation, media
# (audio/video master) and account-workspace endpoints are unmapped rather
# than inferred.
# ---------------------------------------------------------------------------

_PAT_ONLY = (
    "Typeform serves this endpoint only to a personal access token; no OAuth "
    "scope unlocks it. Connect a Typeform Personal Access Token credential."
)


def _typeform_pat() -> ScopeRequirement:
    return ScopeRequirement(credential_types=("typeform_pat",), note=_PAT_ONLY)


_TYPEFORM: dict[str, ScopeRequirement] = {
    # -- forms -----------------------------------------------------------
    "list_forms": _s("forms:read"),
    "get_form": _s("forms:read"),
    "create_form": _s("forms:write"),
    "update_form": _s("forms:write"),
    "delete_form": _s("forms:write"),
    "get_form_custom_messages": _s("forms:read"),
    "update_form_custom_messages": _s("forms:write"),
    # -- themes ----------------------------------------------------------
    "list_themes": _s("themes:read"),
    "get_theme": _s("themes:read"),
    "create_theme": _s("themes:write"),
    "update_theme": _s("themes:write"),
    "delete_theme": _s("themes:write"),
    # -- images ----------------------------------------------------------
    "list_images": _s("images:read"),
    "get_image": _s("images:read"),
    "upload_image": _s("images:write"),
    "delete_image": _s("images:write"),
    # -- workspaces ------------------------------------------------------
    "list_workspaces": _s("workspaces:read"),
    "get_workspace": _s("workspaces:read"),
    "create_workspace": _s("workspaces:write"),
    "update_workspace": _s("workspaces:write"),
    "delete_workspace": _s("workspaces:write"),
    # -- responses -------------------------------------------------------
    "get_form_responses": _s("responses:read"),
    "delete_form_responses": _s("responses:write"),
    "download_response_files": _typeform_pat(),
    "get_response_file": _typeform_pat(),
    # -- webhooks --------------------------------------------------------
    "create_form_webhook": _s("webhooks:write"),
    "update_form_webhook": _s("webhooks:write"),
    "delete_form_webhook": _s("webhooks:write"),
    "list_form_webhooks": _s("webhooks:read"),
    "get_form_webhook": _s("webhooks:read"),
    # Registering the subscription is the only scoped step — Typeform pushes
    # the response payload, so delivery needs no responses:read.
    "on_new_form_response": _s("webhooks:write"),
}

TYPEFORM_SCOPES = ScopeRegistry(
    provider="typeform",
    requirements=_TYPEFORM,
    unmapped=(
        # Translations API: absent from the scopes table and its reference
        # pages state no scope. forms:* is plausible but unstated.
        "get_form_translation_statuses",
        "get_form_translation",
        "create_form_translation",
        "update_form_translation",
        "auto_translate_form_to_language",
        "delete_form_translation",
        # Media service (video upload, audio/video master generation).
        # Undocumented scope; also served from a different path prefix than
        # this node calls, so it may be broken for reasons beyond scopes.
        "upload_video",
        "request_audio_master_generation",
        "get_generated_audio_master",
        "request_video_master_generation",
        "get_generated_video_master",
        # Account-level workspace endpoints: enterprise-only, no scope stated.
        "list_account_workspaces",
        "create_account_workspace",
        # No such endpoint appears in Typeform's published reference.
        "get_form_insights",
    ),
    # NOTE: `offline` is deliberately NOT requested. NoClick's registered
    # Typeform app is a PAT-style app; requesting `offline` makes token
    # exchange fail with "this kind of access tokens cannot have refresh
    # tokens". Do not re-add it as an extra_scope (regression 2026-08-04).
)


# ---------------------------------------------------------------------------
# Dropbox — scopes transcribed from Dropbox's own API spec: every route in
# https://github.com/dropbox/dropbox-api-spec carries a `scope = "..."`
# attribute, surfaced per method in the generated SDK
# (https://github.com/dropbox/dropbox-sdk-python `dropbox/base.py`).
# ---------------------------------------------------------------------------

_DROPBOX: dict[str, ScopeRequirement] = {
    # -- file content ----------------------------------------------------
    "upload_file": _s("files.content.write"),
    "upload_large_file_with_sessions": _s("files.content.write"),
    "create_folder": _s("files.content.write"),
    "delete_file_or_folder": _s("files.content.write"),
    "copy_file_or_folder": _s("files.content.write"),
    "move_file_or_folder": _s("files.content.write"),
    "restore_file_to_revision": _s("files.content.write"),
    "save_url_to_dropbox": _s("files.content.write"),
    "download_file": _s("files.content.read"),
    "download_folder_as_zip": _s("files.content.read"),
    "get_temporary_download_link": _s("files.content.read"),
    "get_file_thumbnail": _s("files.content.read"),
    # -- file metadata ---------------------------------------------------
    "list_folder_contents": _s("files.metadata.read"),
    "search_files_and_folders": _s("files.metadata.read"),
    "get_file_or_folder_metadata": _s("files.metadata.read"),
    "list_file_revisions": _s("files.metadata.read"),
    "add_custom_properties_to_file": _s("files.metadata.write"),
    "update_custom_properties": _s("files.metadata.write"),
    "remove_custom_properties": _s("files.metadata.write"),
    # -- sharing ---------------------------------------------------------
    "create_shared_link": _s("sharing.write"),
    "revoke_shared_link": _s("sharing.write"),
    "share_folder_with_members": _s("sharing.write"),
    "add_members_to_shared_folder": _s("sharing.write"),
    "remove_shared_folder_member": _s("sharing.write"),
    "update_shared_folder_member_access": _s("sharing.write"),
    "mount_shared_folder": _s("sharing.write"),
    "unmount_shared_folder": _s("sharing.write"),
    "unshare_folder": _s("sharing.write"),
    "share_file_with_members": _s("sharing.write"),
    "remove_file_member": _s("sharing.write"),
    "list_shared_links": _s("sharing.read"),
    "list_shared_folder_members": _s("sharing.read"),
    "get_shared_folder_metadata": _s("sharing.read"),
    "list_file_members": _s("sharing.read"),
    # -- file requests ---------------------------------------------------
    "create_file_request": _s("file_requests.write"),
    "update_file_request": _s("file_requests.write"),
    "delete_file_request": _s("file_requests.write"),
    "list_file_requests": _s("file_requests.read"),
    "get_file_request": _s("file_requests.read"),
    "count_file_requests": _s("file_requests.read"),
    # -- account ---------------------------------------------------------
    "get_account_info": _s("account_info.read"),
    "get_account_space_usage": _s("account_info.read"),
}

DROPBOX_SCOPES = ScopeRegistry(
    provider="dropbox",
    requirements=_DROPBOX,
)


# ---------------------------------------------------------------------------
# Box — https://developer.box.com/guides/api-calls/permissions-and-errors/scopes/
#
# Box scopes are application-wide and coarse; its OpenAPI declares the scope
# list globally but attaches no scopes array to individual endpoints, so the
# mapping below is at the granularity Box actually documents:
#   root_readwrite  "Read and write all files and folders stored in Box"
#                   (explicitly includes read, and names collaborations)
#   manage_webhook  "Create webhooks for a user"
#   manage_managed_users  "Provision and manage managed users"
#
# The read-only operations would also be satisfied by `root_readonly`, which
# the node does not request; `root_readwrite` subsumes it, so that is what is
# declared. `manage_groups` and `manage_enterprise_properties` are requested
# but no operation here uses them.
# ---------------------------------------------------------------------------

_BOX_CONTENT = _s("root_readwrite")
_BOX_WEBHOOK = _s("manage_webhook")

_BOX: dict[str, ScopeRequirement] = {
    # -- folders ---------------------------------------------------------
    "list_folder_items": _BOX_CONTENT,
    "get_folder": _BOX_CONTENT,
    "create_folder": _BOX_CONTENT,
    "update_folder": _BOX_CONTENT,
    "delete_folder": _BOX_CONTENT,
    "copy_folder": _BOX_CONTENT,
    "list_trash": _BOX_CONTENT,
    "create_folder_shared_link": _BOX_CONTENT,
    # -- files -----------------------------------------------------------
    "get_file": _BOX_CONTENT,
    "get_download_url": _BOX_CONTENT,
    "upload_file": _BOX_CONTENT,
    "upload_version": _BOX_CONTENT,
    "update_file": _BOX_CONTENT,
    "delete_file": _BOX_CONTENT,
    "copy_file": _BOX_CONTENT,
    "create_file_shared_link": _BOX_CONTENT,
    "search": _BOX_CONTENT,
    # -- collaboration ---------------------------------------------------
    "add_collaboration": _BOX_CONTENT,
    "list_collaborations": _BOX_CONTENT,
    "remove_collaboration": _BOX_CONTENT,
    "add_comment": _BOX_CONTENT,
    "list_comments": _BOX_CONTENT,
    "create_task": _BOX_CONTENT,
    # -- users -----------------------------------------------------------
    # GET /users/me declares no scope; the enterprise user list needs the
    # managed-user scope plus an admin-capable account.
    "get_me": _s(),
    "list_users": _s("manage_managed_users"),
    # -- webhooks --------------------------------------------------------
    "create_webhook": _BOX_WEBHOOK,
    "list_webhooks": _BOX_WEBHOOK,
    "delete_webhook": _BOX_WEBHOOK,
    "on_box_event": _BOX_WEBHOOK,
}

BOX_SCOPES = ScopeRegistry(provider="box", requirements=_BOX)
