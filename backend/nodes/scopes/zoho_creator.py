"""Zoho Creator scopes from the provider's v2.1 OAS and OAuth overview.

https://www.zoho.com/creator/help/api/v2.1/oauth-overview.html
https://www.zoho.com/developer/oauth/web-server-apps/get-authorization-code.html
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

ZOHO_CREATOR_SCOPES = ScopeRegistry(
    provider="zoho_creator",
    requirements={
        **{op: ScopeRequirement(("ZohoCreator.dashboard.READ",)) for op in (
            "list_applications", "list_workspace_applications")},
        **{op: ScopeRequirement(("ZohoCreator.meta.application.READ",)) for op in (
            "list_forms", "list_reports", "list_pages", "list_sections")},
        "list_fields": ScopeRequirement(("ZohoCreator.meta.form.READ",)),
        **{op: ScopeRequirement(("ZohoCreator.report.READ",)) for op in ("list_records", "get_record")},
        "add_records": ScopeRequirement(("ZohoCreator.form.CREATE",)),
        **{op: ScopeRequirement(("ZohoCreator.report.UPDATE",)) for op in ("update_record", "update_records")},
        **{op: ScopeRequirement(("ZohoCreator.report.DELETE",)) for op in ("delete_record", "delete_records")},
        **{op: ScopeRequirement(("ZohoCreator.bulk.CREATE",)) for op in ("create_bulk_read",)},
        **{op: ScopeRequirement(("ZohoCreator.bulk.READ",)) for op in ("get_bulk_read", "get_bulk_insert")},
    },
    extra_scopes={"default": ("aaaserver.profile.READ",)},
    enforcement=Enforcement.STRICT,
)
