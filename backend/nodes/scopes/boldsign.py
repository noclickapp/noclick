"""BoldSign machine API requirements, keyed by the protected endpoint.

Official scope reference: https://developers.boldsign.com/authentication/introduction/?region=us
Templates.All satisfies Read and Write. Contacts have no documented dedicated scope;
those endpoints remain provider-enforced rather than inventing a permission.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

_DOCUMENT = ScopeRequirement(scopes=("BoldSign.Documents.All",))
_READ = ScopeRequirement(scopes=("BoldSign.Templates.Read",))
_WRITE = ScopeRequirement(scopes=("BoldSign.Templates.Write",))
_CONTACT = ScopeRequirement(note="No documented contact scope; provider permissions remain authoritative")

BOLDSIGN_SCOPES = ScopeRegistry("boldsign", {
    **{path: _DOCUMENT for path in ("/v1/document/list", "/v1/document/properties", "/v1/document/addTags", "/v1/document/deleteTags")},
    **{path: _READ for path in ("/v1/template/list", "/v1/template/properties")},
    **{path: _WRITE for path in ("/v1/template/addTags", "/v1/template/deleteTags")},
    **{path: _CONTACT for path in ("/v1/contacts/list", "/v1/contacts/get", "/v1/contacts/create", "/v1/contacts/update", "/v1/contacts/delete", "/v1/contactGroups/list", "/v1/contactGroups/get")},
})

# Preflight the full operation before minting a token, including selected-resource reads.
OPERATION_ENDPOINTS = {
    "check_connection": ("/v1/document/list",), "list_documents": ("/v1/document/list",),
    **{op: ("/v1/document/properties",) for op in ("get_document", "get_document_status", "get_document_history")},
    "list_templates": ("/v1/template/list",), "get_template": ("/v1/template/properties",),
    "list_contacts": ("/v1/contacts/list",), "get_contact": ("/v1/contacts/get",),
    "create_contact": ("/v1/contacts/create",), "update_contact": ("/v1/contacts/update",), "delete_contact": ("/v1/contacts/delete",),
    "list_contact_groups": ("/v1/contactGroups/list",), "get_contact_group": ("/v1/contactGroups/get",),
    **{f"{action}_{kind}_tags": (f"/v1/{kind}/properties", f"/v1/{kind}/{endpoint}")
       for kind in ("document", "template") for action, endpoint in (("add", "addTags"), ("delete", "deleteTags"))},
}


def require_machine_scopes(scopes, endpoints):
    granted = set(scopes)
    # Normalize the documented alternative without broadening the requested token scopes.
    if "BoldSign.Templates.All" in granted:
        granted.update(("BoldSign.Templates.Read", "BoldSign.Templates.Write"))
    for endpoint in endpoints:
        if not set(BOLDSIGN_SCOPES.require(endpoint).scopes).issubset(granted):
            raise ValueError("Select the documented API scopes for this operation")
