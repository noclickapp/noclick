"""Company API v2 scopes, using the full-access alternative for read/write workflows.

https://pennylane.readme.io/docs/firm-api documents GET's readonly OR all
semantics. The published contract incorrectly puts both in one OAuth array
(AND). Read-only tokens also work for reads; no OAuth grants are requested here.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

PENNYLANE_SCOPES = ScopeRegistry("pennylane", {
    'get_me': ScopeRequirement(scopes=()),
    'list_customers': ScopeRequirement(scopes=('customers:all',)),
    'get_customer': ScopeRequirement(scopes=('customers:all',)),
    'list_suppliers': ScopeRequirement(scopes=('suppliers:all',)),
    'get_supplier': ScopeRequirement(scopes=('suppliers:all',)),
    'list_products': ScopeRequirement(scopes=('products:all',)),
    'get_product': ScopeRequirement(scopes=('products:all',)),
    'list_customer_invoices': ScopeRequirement(scopes=('customer_invoices:all',)),
    'get_customer_invoice': ScopeRequirement(scopes=('customer_invoices:all',)),
    'list_supplier_invoices': ScopeRequirement(scopes=('supplier_invoices:all',)),
    'get_supplier_invoice': ScopeRequirement(scopes=('supplier_invoices:all',)),
    'list_transactions': ScopeRequirement(scopes=('transactions:all',)),
    'get_transaction': ScopeRequirement(scopes=('transactions:all',)),
    'list_bank_accounts': ScopeRequirement(scopes=('bank_accounts:all',)),
    'create_company_customer': ScopeRequirement(scopes=('customers:all',)),
    'update_company_customer': ScopeRequirement(scopes=('customers:all',)),
    'create_individual_customer': ScopeRequirement(scopes=('customers:all',)),
    'update_individual_customer': ScopeRequirement(scopes=('customers:all',)),
    'create_supplier': ScopeRequirement(scopes=('suppliers:all',)),
    'update_supplier': ScopeRequirement(scopes=('suppliers:all',)),
    'create_product': ScopeRequirement(scopes=('products:all',)),
    'update_product': ScopeRequirement(scopes=('products:all',)),
    'create_customer_invoice': ScopeRequirement(scopes=('customer_invoices:all',)),
    'mark_customer_invoice_paid': ScopeRequirement(scopes=('customer_invoices:all',)),
    'update_supplier_invoice_payment_status': ScopeRequirement(scopes=('supplier_invoices:all',)),
})
