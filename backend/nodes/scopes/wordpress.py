"""WordPress.com operation → OAuth scope requirements.

WordPress.com's OAuth2 does define granular scopes — ``posts``, ``comments``,
``taxonomy``, ``media``, ``users``, ``sites``, ``stats``, ``menus``, … — plus two
special ones: ``auth`` (``/me/`` only, for "Sign in with WordPress.com") and
``global``, which "grants comprehensive access to user data across all
WordPress.com services and connected sites".

This node requests ``global``, which subsumes every granular scope, so the
per-operation requirement that is *observable on this credential* is ``global``
for all of them. Mapping the granular names instead would be strictly wrong
here: they are not in the requested list, and the coverage check has no notion
of a scope that implies others. If the node is ever moved to least privilege,
the granular mapping is: posts/pages → ``posts``, comments → ``comments``,
categories/tags → ``taxonomy``, media → ``media``, users → ``users``, site
settings → ``sites``.

Self-hosted WordPress (application password / basic auth credentials) has no
OAuth scope model at all; this table describes the WordPress.com OAuth
credential only.

Docs: https://developer.wordpress.com/docs/oauth2/
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: WordPress.com's all-access scope, the only one this node requests.
GLOBAL = ScopeRequirement(scopes=("global",))

_OPERATIONS = (
    # Posts
    "list_posts",
    "get_post",
    "create_post",
    "update_post",
    "delete_post",
    "search_content",
    # Pages
    "list_pages",
    "get_page",
    "create_page",
    "update_page",
    "delete_page",
    # Media
    "list_media_items",
    "get_media_item",
    "upload_media_file",
    "update_media_metadata",
    "delete_media_item",
    # Users
    "list_users",
    "get_user",
    "create_user",
    "update_user",
    "delete_user",
    # Comments
    "list_comments",
    "get_comment",
    "create_post_comment",
    "update_comment",
    "delete_comment",
    # Taxonomy
    "list_categories",
    "get_category",
    "create_category",
    "update_category",
    "delete_category",
    "list_tags",
    "get_tag",
    "create_tag",
    "update_tag",
    "delete_tag",
    # Site settings
    "get_site_settings",
    "update_site_settings",
)

_REQUIREMENTS = {operation: GLOBAL for operation in _OPERATIONS}

WORDPRESS_SCOPES = ScopeRegistry(
    provider="wordpress",
    requirements=_REQUIREMENTS,
)
