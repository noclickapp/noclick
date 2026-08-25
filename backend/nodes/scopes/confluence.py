"""Confluence operation → OAuth scope requirements.

Derived from Atlassian's published OpenAPI specs — Confluence v2
(``openapi-v2.v3.json``) and v1 (``swagger.v3.json``) — by resolving each
operation's handler to the endpoint it calls and reading that endpoint's
``security`` entry. Every scope here is Atlassian's own declaration.

Two quirks drive the shape:

- **The node straddles two API surfaces.** Most handlers use v2
  (``/wiki/api/v2``), which declares GRANULAR scopes (``read:page:confluence``).
  CQL search, attachment upload, add/remove label, and current-user still only
  exist on v1 (``/wiki/rest/api``), which declares CLASSIC scopes
  (``search:confluence``, ``write:confluence-file``, ``write:confluence-content``,
  ``read:confluence-user``). The two families are not interchangeable, which is
  why the node requests both.
- **Blog posts ride the page scopes.** Atlassian's v2 spec declares
  ``read:/write:/delete:page:confluence`` on ``/blogposts`` — not the
  ``blogpost`` scopes it also defines. Mapped as the spec says, not as the
  scope name suggests.

Every operation is mapped: nothing this node calls needs a scope it does not
already request.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- v2 pages (blog posts included, per the spec) --------------------
    "list_pages": _s("read:page:confluence"),
    "get_page": _s("read:page:confluence"),
    "create_page": _s("write:page:confluence"),
    "update_page": _s("write:page:confluence"),
    "delete_page": _s("delete:page:confluence"),
    "list_pages_in_space": _s("read:page:confluence"),
    "list_child_pages": _s("read:page:confluence"),
    "get_page_versions": _s("read:page:confluence"),
    "list_page_labels": _s("read:page:confluence"),
    # Walks the parentId chain via GET /pages/{id} rather than
    # GET /pages/{id}/ancestors, which needs read:content.metadata:confluence.
    "get_page_ancestors": _s("read:page:confluence"),
    "list_blog_posts": _s("read:page:confluence"),
    "get_blog_post": _s("read:page:confluence"),
    "create_blog_post": _s("write:page:confluence"),
    "update_blog_post": _s("write:page:confluence"),
    "delete_blog_post": _s("delete:page:confluence"),
    # Polls GET /pages and GET /blogposts.
    "on_new_content": _s("read:page:confluence"),

    # -- v2 content properties: read+write on the owning page ------------
    "list_content_properties": _s("read:page:confluence"),
    "create_content_property": _s("read:page:confluence", "write:page:confluence"),
    "update_content_property": _s("read:page:confluence", "write:page:confluence"),
    "delete_content_property": _s("read:page:confluence", "write:page:confluence"),

    # -- v2 comments ------------------------------------------------------
    "list_footer_comments": _s("read:comment:confluence"),
    "list_inline_comments": _s("read:comment:confluence"),
    "list_blog_post_footer_comments": _s("read:comment:confluence"),
    "list_blog_post_inline_comments": _s("read:comment:confluence"),
    "create_footer_comment": _s("write:comment:confluence"),
    "create_inline_comment": _s("write:comment:confluence"),
    "update_footer_comment": _s("write:comment:confluence"),
    "update_inline_comment": _s("write:comment:confluence"),
    "delete_footer_comment": _s("delete:comment:confluence"),
    "delete_inline_comment": _s("delete:comment:confluence"),

    # -- v2 attachments (upload is v1-only, below) -----------------------
    "list_attachments": _s("read:attachment:confluence"),
    "get_attachment": _s("read:attachment:confluence"),
    "delete_attachment": _s("delete:attachment:confluence"),

    # -- v2 spaces --------------------------------------------------------
    "list_spaces": _s("read:space:confluence"),
    "get_space": _s("read:space:confluence"),
    "create_space": _s("write:space:confluence"),
    "list_space_labels": _s("read:space:confluence"),

    # -- v2 tasks ---------------------------------------------------------
    "list_tasks": _s("read:task:confluence"),
    "get_task": _s("read:task:confluence"),
    "update_task": _s("write:task:confluence"),

    # -- v1 surfaces with no v2 equivalent yet (classic scopes) ----------
    "search": _s("search:confluence"),
    "search_content": _s("search:confluence"),
    "get_current_user": _s("read:confluence-user"),
    "add_label": _s("write:confluence-content"),
    "remove_label": _s("write:confluence-content"),
    "upload_attachment": _s("write:confluence-file"),
}

CONFLUENCE_SCOPES = ScopeRegistry(
    provider="confluence",
    requirements=_REQUIREMENTS,
)
