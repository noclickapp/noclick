"""Content/storage providers → OAuth scope requirements.

Grouped because Canva, Typeform, Dropbox and Box all scope a token by
*resource family × read/write* over user content — designs and assets, forms
and responses, files and folders. The strings differ in punctuation
(``asset:write``, ``forms:write``, ``files.content.write``, ``root_readwrite``)
but the shape, and therefore the reviewing work, is the same.

Canva and Dropbox keep their registries in ``canva.py`` and ``dropbox.py``.
All four run at ``Enforcement.SUBSET``: the tables cover only what the
providers publish, and several operations sit in ``unmapped`` because the
provider documents no scope for them at all.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


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
