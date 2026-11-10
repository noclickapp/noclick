"""Scopes from Zoho Books' official per-operation OpenAPI security requirements."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.zoho_books_operations import OPERATIONS

ZOHO_BOOKS_SCOPES = ScopeRegistry(
    provider="zoho_books",
    requirements={**{name: ScopeRequirement(scopes=tuple(op["scopes"])) for name, op in OPERATIONS.items()},
        "on_invoice_updated": ScopeRequirement(("ZohoBooks.invoices.READ",)),
        "on_contact_updated": ScopeRequirement(("ZohoBooks.contacts.READ",)),
        "on_payment_updated": ScopeRequirement(("ZohoBooks.customerpayments.READ",))},
    extra_scopes={"default": ("AaaServer.profile.READ",)},
)
