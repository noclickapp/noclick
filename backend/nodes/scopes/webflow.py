"""Webflow operation → OAuth scope requirements.

Webflow scopes are per-resource ``<resource>:read`` / ``<resource>:write``
pairs, and the resource is the one the endpoint path names: ``/sites`` →
``sites``, ``/collections`` → ``cms``, ``/pages`` → ``pages``, ``/forms`` and
``/form_submissions`` → ``forms``, ``/assets`` and ``/asset_folders`` →
``assets``, ``/products`` ``/orders`` ``/inventory`` ``/ecommerce`` →
``ecommerce``, ``/comments`` → ``comments``, ``/components`` → ``components``,
``/custom_code`` and ``/registered_scripts`` → ``custom_code``. Reads take
``:read``, mutations take ``:write``; spot-verified against the published
reference for publish-site (``sites:write``), get-custom-domains
(``sites:read``), get/update page content (``pages:read`` / ``pages:write``),
list-inventory (``ecommerce:read``), register-hosted-script
(``custom_code:write``) and create-webhook (``sites:write``).

Two endpoints sit outside the resource grid: ``/token/authorized_by`` needs
``authorized_user:read``, and ``/token/introspect`` needs no scope at all
("Authorization info | None required").

Trigger operations register a webhook (``POST /sites/{id}/webhooks``), which is
``sites:write``. Webflow additionally documents the webhooks row as "Depends on
``trigger_type``" without publishing the per-trigger table, so the scope that
authorizes *delivery* of each event type is not mapped here. That is not a gap
in practice: the node already requests every data scope a trigger could plausibly
need (``cms``, ``forms``, ``ecommerce``, ``comments``, ``pages``, all read).

``custom_code:*`` is Data-Client-app only — a Site Token credential cannot use
the custom-code operations regardless of this table.

Docs: https://developers.webflow.com/data/reference/scopes
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_SITES_READ = _s("sites:read")
_SITES_WRITE = _s("sites:write")
_PAGES_READ = _s("pages:read")
_PAGES_WRITE = _s("pages:write")
_CMS_READ = _s("cms:read")
_CMS_WRITE = _s("cms:write")
_FORMS_READ = _s("forms:read")
_FORMS_WRITE = _s("forms:write")
_ASSETS_READ = _s("assets:read")
_ASSETS_WRITE = _s("assets:write")
_ECOMM_READ = _s("ecommerce:read")
_ECOMM_WRITE = _s("ecommerce:write")
_COMMENTS_READ = _s("comments:read")
_COMPONENTS_READ = _s("components:read")
_COMPONENTS_WRITE = _s("components:write")
_CUSTOM_CODE_READ = _s("custom_code:read")
_CUSTOM_CODE_WRITE = _s("custom_code:write")


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Sites ---------------------------------------------------------
    "list_sites": _SITES_READ,
    "get_site": _SITES_READ,
    "get_custom_domains": _SITES_READ,
    "publish_site": _SITES_WRITE,
    # -- Pages ---------------------------------------------------------
    "list_pages": _PAGES_READ,
    "get_page_content": _PAGES_READ,
    "get_page_metadata": _PAGES_READ,
    "update_page_content": _PAGES_WRITE,
    "update_page_metadata": _PAGES_WRITE,
    # -- Components ----------------------------------------------------
    "list_components": _COMPONENTS_READ,
    "get_component_content": _COMPONENTS_READ,
    "get_component_properties": _COMPONENTS_READ,
    "update_component_content": _COMPONENTS_WRITE,
    "update_component_properties": _COMPONENTS_WRITE,
    # -- CMS: collections ----------------------------------------------
    "list_collections": _CMS_READ,
    "get_collection": _CMS_READ,
    "create_collection": _CMS_WRITE,
    "delete_collection": _CMS_WRITE,
    "create_collection_field": _CMS_WRITE,
    "update_collection_field": _CMS_WRITE,
    "delete_collection_field": _CMS_WRITE,
    # -- CMS: items ----------------------------------------------------
    "list_items": _CMS_READ,
    "get_item": _CMS_READ,
    "list_live_items": _CMS_READ,
    "get_live_item": _CMS_READ,
    "create_item": _CMS_WRITE,
    "create_live_item": _CMS_WRITE,
    "create_bulk_items": _CMS_WRITE,
    "update_item": _CMS_WRITE,
    "update_live_item": _CMS_WRITE,
    "delete_item": _CMS_WRITE,
    "delete_live_item": _CMS_WRITE,
    "publish_items": _CMS_WRITE,
    # -- Forms ---------------------------------------------------------
    "list_forms": _FORMS_READ,
    "get_form": _FORMS_READ,
    "list_form_submissions": _FORMS_READ,
    "list_site_form_submissions": _FORMS_READ,
    "get_form_submission": _FORMS_READ,
    "modify_submission": _FORMS_WRITE,
    "delete_submission": _FORMS_WRITE,
    # -- Assets --------------------------------------------------------
    "list_assets": _ASSETS_READ,
    "get_asset": _ASSETS_READ,
    "list_asset_folders": _ASSETS_READ,
    "get_asset_folder": _ASSETS_READ,
    "create_asset": _ASSETS_WRITE,
    "update_asset": _ASSETS_WRITE,
    "delete_asset": _ASSETS_WRITE,
    "create_asset_folder": _ASSETS_WRITE,
    # -- Ecommerce -----------------------------------------------------
    "list_products": _ECOMM_READ,
    "get_product": _ECOMM_READ,
    "list_orders": _ECOMM_READ,
    "get_order": _ECOMM_READ,
    "list_inventory": _ECOMM_READ,
    "get_ecommerce_settings": _ECOMM_READ,
    "create_product": _ECOMM_WRITE,
    "update_product": _ECOMM_WRITE,
    "create_skus": _ECOMM_WRITE,
    "update_sku": _ECOMM_WRITE,
    "update_inventory": _ECOMM_WRITE,
    "update_order": _ECOMM_WRITE,
    "fulfill_order": _ECOMM_WRITE,
    "unfulfill_order": _ECOMM_WRITE,
    "refund_order": _ECOMM_WRITE,
    # -- Comments (read-only surface on this node) ----------------------
    "list_comment_threads": _COMMENTS_READ,
    "get_comment_thread": _COMMENTS_READ,
    "list_comment_replies": _COMMENTS_READ,
    # -- Custom code (Data Client apps only) ----------------------------
    "get_site_custom_code": _CUSTOM_CODE_READ,
    "get_page_custom_code": _CUSTOM_CODE_READ,
    "list_registered_scripts": _CUSTOM_CODE_READ,
    "apply_site_custom_code": _CUSTOM_CODE_WRITE,
    "remove_site_custom_code": _CUSTOM_CODE_WRITE,
    "apply_page_custom_code": _CUSTOM_CODE_WRITE,
    "remove_page_custom_code": _CUSTOM_CODE_WRITE,
    "register_hosted_script": _CUSTOM_CODE_WRITE,
    "register_inline_script": _CUSTOM_CODE_WRITE,
    # -- Token ----------------------------------------------------------
    "get_authorized_user": _s("authorized_user:read"),
    # "Authorization info | None required" — authentication is enough.
    "introspect_token": _s(),
    # -- Webhooks -------------------------------------------------------
    "list_webhooks": _SITES_READ,
    "get_webhook": _SITES_READ,
    "create_webhook": _SITES_WRITE,
    "remove_webhook": _SITES_WRITE,
    # -- Triggers: each registers POST /sites/{id}/webhooks --------------
    "form_submission": _SITES_WRITE,
    "site_publish": _SITES_WRITE,
    "page_created": _SITES_WRITE,
    "page_metadata_updated": _SITES_WRITE,
    "page_deleted": _SITES_WRITE,
    "collection_item_created": _SITES_WRITE,
    "collection_item_changed": _SITES_WRITE,
    "collection_item_deleted": _SITES_WRITE,
    "collection_item_published": _SITES_WRITE,
    "collection_item_unpublished": _SITES_WRITE,
    "ecomm_new_order": _SITES_WRITE,
    "ecomm_order_changed": _SITES_WRITE,
    "ecomm_inventory_changed": _SITES_WRITE,
    "comment_created": _SITES_WRITE,
}

WEBFLOW_SCOPES = ScopeRegistry(
    provider="webflow",
    requirements=_REQUIREMENTS,
)
