"""Qonto OAuth permissions from the Business API endpoint access table.
The shared registry requests the scopes needed by actions, webhooks and token refresh.

https://docs.qonto.com/api-reference/business-api/introduction/authentication/scopes
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

QONTO_SCOPES = ScopeRegistry(
    provider="qonto",
    extra_scopes={"default": ("offline_access", "organization.read")},
    requirements={
        'get_organization': ScopeRequirement(('organization.read',)),
        'list_transactions': ScopeRequirement(('organization.read',)),
        'get_transaction': ScopeRequirement(('organization.read',)),
        'list_labels': ScopeRequirement(('organization.read',)),
        'list_memberships': ScopeRequirement(('organization.read',)),
        'list_beneficiaries': ScopeRequirement(('organization.read',)),
        'get_beneficiary': ScopeRequirement(('organization.read',)),
        'list_supplier_invoices': ScopeRequirement(('supplier_invoice.read',)),
        'get_supplier_invoice': ScopeRequirement(('supplier_invoice.read',)),
        'mark_supplier_invoice_as_paid': ScopeRequirement(('supplier_invoice.write',)),
        'unmark_supplier_invoice_as_paid': ScopeRequirement(('supplier_invoice.write',)),
        'list_clients': ScopeRequirement(('client.read',)),
        'get_client': ScopeRequirement(('client.read',)),
        'list_products': ScopeRequirement(('product.read',)),
        'get_product': ScopeRequirement(('product.read',)),
        'list_client_invoices': ScopeRequirement(('client_invoices.read',)),
        'get_client_invoice': ScopeRequirement(('client_invoices.read',)),
        'list_statements': ScopeRequirement(('organization.read',)),
        'create_client': ScopeRequirement(('client.write',)),
        'update_client': ScopeRequirement(('client.write',)),
        'delete_client': ScopeRequirement(('client.write',)),
        'create_product': ScopeRequirement(('product.write',)),
        'delete_product': ScopeRequirement(('product.write',)),
        'on_transaction': ScopeRequirement(('webhook', 'organization.read')),
        'on_client_invoice': ScopeRequirement(('webhook', 'client_invoices.read')),
    },
)
