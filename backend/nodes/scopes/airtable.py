"""Airtable operation → OAuth scope requirements.

Airtable publishes a scope per endpoint (https://airtable.com/developers/web/api/scopes),
so this table is a straight transcription. Three things shape it:

- **Record comments have their own scope pair.** ``data.recordComments:read`` /
  ``data.recordComments:write`` are separate from ``data.records:*``; the four
  comment operations returned INVALID_PERMISSIONS until they were added to the
  request.
- **Webhook scopes depend on the subscription.** Every webhook endpoint needs
  ``webhook:manage``. ``create webhook`` and ``list payloads`` additionally need
  ``data.records:read`` for a ``tableData`` subscription and
  ``schema.bases:read`` for ``tableFields``/``tableMetadata``. The dataTypes are
  chosen at run time from user config, so those two declare the union — the
  narrower case simply asks for more than it uses.
- **PATs use the same vocabulary.** The Personal Access Token credential carries
  the identical scope strings, so this table describes both credential types.

Every operation is mapped and the derived union equals the requested list, so
enforcement is ``STRICT``: the request cannot grow a scope no operation needs,
nor shrink below one.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_RECORDS_READ = _s("data.records:read")
_RECORDS_WRITE = _s("data.records:write")
_SCHEMA_READ = _s("schema.bases:read")
_SCHEMA_WRITE = _s("schema.bases:write")
_COMMENTS_READ = _s("data.recordComments:read")
_COMMENTS_WRITE = _s("data.recordComments:write")
_WEBHOOK = _s("webhook:manage")
# Create-webhook and list-payloads add a per-dataType scope; the subscription is
# user config, so declare every dataType the node can request.
_WEBHOOK_WITH_DATA = _s("webhook:manage", "data.records:read", "schema.bases:read")


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- bases and schema (/v0/meta) ------------------------------------
    "list_accessible_bases": _SCHEMA_READ,
    "fetch_base_schema": _SCHEMA_READ,
    "create_new_table": _SCHEMA_WRITE,
    "update_table_metadata": _SCHEMA_WRITE,
    "create_table_field": _SCHEMA_WRITE,
    "update_table_field": _SCHEMA_WRITE,
    # -- records --------------------------------------------------------
    "list_table_records": _RECORDS_READ,
    "fetch_single_record": _RECORDS_READ,
    "create_multiple_records": _RECORDS_WRITE,
    "update_single_record": _RECORDS_WRITE,
    "update_multiple_records": _RECORDS_WRITE,
    # Upsert is the update-multiple endpoint with performUpsert; Airtable
    # documents no extra scope for the merge behaviour.
    "upsert_records_by_field_match": _RECORDS_WRITE,
    "delete_single_record": _RECORDS_WRITE,
    "delete_multiple_records": _RECORDS_WRITE,
    # -- record comments ------------------------------------------------
    "list_record_comments": _COMMENTS_READ,
    "create_record_comment": _COMMENTS_WRITE,
    "update_record_comment": _COMMENTS_WRITE,
    "delete_record_comment": _COMMENTS_WRITE,
    # -- webhooks -------------------------------------------------------
    "list_base_webhooks": _WEBHOOK,
    "create_base_webhook": _WEBHOOK_WITH_DATA,
    "delete_base_webhook": _WEBHOOK,
    "list_webhook_payloads": _WEBHOOK_WITH_DATA,
    "refresh_webhook_expiration": _WEBHOOK,
    "enable_webhook_notifications": _WEBHOOK,
}


AIRTABLE_SCOPES = ScopeRegistry(
    provider="airtable",
    requirements=_REQUIREMENTS,
    enforcement=Enforcement.STRICT,
)
