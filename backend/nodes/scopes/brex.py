"""User-token permissions from Brex's official OpenAPI security declarations.

https://developer.brex.com/guides/roles_permissions_scopes
This table preserves the literal scope arrays in the pinned official specs.
Brex describes readonly/write scopes as alternatives in its guide, while its
OpenAPI encodes them as conjunctions. These are manual tokens, not an OAuth
consent request; the user chooses permissions in Developer settings.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

BREX_SCOPES = ScopeRegistry(
    "brex",
    {
        "on_expense_payment_updated": ScopeRequirement(("expenses.card.readonly", "expenses.card")),
        "on_transfer_processed": ScopeRequirement(("transfers.readonly", "transfers")),
        "list_expenses": ScopeRequirement(("expenses.card.readonly", "expenses.card")),
        "get_expense": ScopeRequirement(("expenses.card.readonly", "expenses.card")),
        "update_expense": ScopeRequirement("expenses.card"),
        "list_cards": ScopeRequirement(("cards.readonly", "cards")),
        "get_card": ScopeRequirement(("cards.readonly", "cards")),
        "create_card": ScopeRequirement("cards"),
        "update_card": ScopeRequirement("cards"),
        "lock_card": ScopeRequirement("cards"),
        "unlock_card": ScopeRequirement("cards"),
        "terminate_card": ScopeRequirement("cards"),
        "list_cash_accounts": ScopeRequirement("accounts.cash.readonly"),
        "get_cash_account": ScopeRequirement("accounts.cash.readonly"),
        "list_card_accounts": ScopeRequirement("accounts.card.readonly"),
        "get_company": ScopeRequirement("companies.readonly"),
        "list_card_transactions": ScopeRequirement("transactions.card.readonly"),
        "list_cash_transactions": ScopeRequirement("transactions.cash.readonly"),
        "list_transfers": ScopeRequirement(
            ("transfers.readonly", "incoming_transfers")
        ),
        "get_transfer": ScopeRequirement(("transfers.readonly", "incoming_transfers")),
        "create_transfer": ScopeRequirement("transfers"),
        "list_vendors": ScopeRequirement("vendors.readonly"),
    },
)
