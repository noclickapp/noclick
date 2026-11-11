"""Required API-key scopes from https://hasslefreebooks.com/openapi.json."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

HASSLEFREEBOOKS_SCOPES = ScopeRegistry(provider="hasslefreebooks", requirements={
    'list_transactions': ScopeRequirement(('read',)),
    'create_transaction': ScopeRequirement(('write',)),
    'get_transaction': ScopeRequirement(('read',)),
    'get_invoice': ScopeRequirement(('read',)),
    'send_invoice': ScopeRequirement(('write',)),
    'get_balance_sheet': ScopeRequirement(('read',)),
    'list_accounts': ScopeRequirement(('read',)),
    'list_contacts': ScopeRequirement(('read',)),
    'create_contact': ScopeRequirement(('write',)),
    'get_contact': ScopeRequirement(('read',)),
    'update_contact': ScopeRequirement(('write',)),
    'get_current_user': ScopeRequirement(('read',)),
    'list_invoices': ScopeRequirement(('read',)),
    'create_invoice': ScopeRequirement(('write',)),
    'list_bills': ScopeRequirement(('read',)),
    'create_bill': ScopeRequirement(('write',)),
    'get_bill': ScopeRequirement(('read',)),
    'pay_bill': ScopeRequirement(('write',)),
    'get_profit_loss': ScopeRequirement(('read',)),
    'record_invoice_payment': ScopeRequirement(('write',)),
    'finalize_invoice': ScopeRequirement(('write',)),
    'approve_bill': ScopeRequirement(('write',)),
    'on_event': ScopeRequirement(('write',)),
})
