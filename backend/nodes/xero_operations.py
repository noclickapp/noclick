"""Xero operation routes from https://github.com/XeroAPI/Xero-OpenAPI."""

import re
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    scope: Optional[str]
    api: str = "accounting"
    body_envelope: Optional[str] = None
    creates: Optional[str] = None
    required_fields: tuple[str, ...] = ()


OPERATIONS: dict[str, Operation] = {
    "list_connections": Operation("List Connected Organisations", "Account", "GET", "/connections", None),
    "get_organisation": Operation("Get Organisation", "Account", "GET", "/Organisation",
                                  "accounting.settings"),
}


def _resource(
    singular: str, plural: str, id_field: str, scope: str, *,
    api: str = "accounting", create: bool = True, update: bool = True,
    delete: bool = False, create_single: bool = False,
) -> None:
    category = re.sub(r"(?<!^)(?=[A-Z])", " ", plural).title()
    plural_key = category.lower().replace(" ", "_")
    endpoint = "/" + plural
    read_scope = scope if create or update or delete else scope + ".read"
    OPERATIONS[f"list_{plural_key}"] = Operation(
        f"List {category}", category, "GET", endpoint, read_scope, api)
    OPERATIONS[f"get_{singular.lower()}"] = Operation(
        f"Get {singular.replace('_', ' ').title()}", category, "GET",
        f"{endpoint}/{{{id_field}}}", read_scope, api,
        required_fields=(id_field,))
    if create:
        OPERATIONS[f"create_{singular.lower()}"] = Operation(
            f"Create {singular.replace('_', ' ').title()}", category, "PUT",
            endpoint, scope, api, None if create_single else plural,
            creates=singular.lower(), required_fields=("record_json",))
    if update:
        OPERATIONS[f"update_{singular.lower()}"] = Operation(
            f"Update {singular.replace('_', ' ').title()}", category, "POST",
            f"{endpoint}/{{{id_field}}}", scope, api, plural,
            required_fields=(id_field, "record_json"))
    if delete:
        OPERATIONS[f"delete_{singular.lower()}"] = Operation(
            f"Delete {singular.replace('_', ' ').title()}", category, "DELETE",
            f"{endpoint}/{{{id_field}}}", scope, api,
            required_fields=(id_field,))


_resource("account", "Accounts", "AccountID", "accounting.settings",
          delete=True, create_single=True)
_resource("bank_transaction", "BankTransactions", "BankTransactionID", "accounting.banktransactions")
_resource("contact", "Contacts", "ContactID", "accounting.contacts")
_resource("credit_note", "CreditNotes", "CreditNoteID", "accounting.invoices")
_resource("invoice", "Invoices", "InvoiceID", "accounting.invoices")
_resource("item", "Items", "ItemID", "accounting.settings", delete=True)
_resource("manual_journal", "ManualJournals", "ManualJournalID", "accounting.manualjournals")
_resource("payment", "Payments", "PaymentID", "accounting.payments", update=False)
_resource("purchase_order", "PurchaseOrders", "PurchaseOrderID", "accounting.invoices")
_resource("quote", "Quotes", "QuoteID", "accounting.invoices")

OPERATIONS.update({
    "list_budgets": Operation("List Budgets", "Budgets", "GET", "/Budgets",
                              "accounting.budgets.read"),
    "get_budget": Operation("Get Budget", "Budgets", "GET", "/Budgets/{BudgetID}",
                            "accounting.budgets.read", required_fields=("BudgetID",)),
    "list_tax_rates": Operation("List Tax Rates", "Settings", "GET", "/TaxRates",
                                "accounting.settings"),
    "list_tracking_categories": Operation("List Tracking Categories", "Settings", "GET",
                                          "/TrackingCategories", "accounting.settings"),
    "get_balance_sheet": Operation("Get Balance Sheet", "Reports", "GET", "/Reports/BalanceSheet",
                                   "accounting.reports.balancesheet.read"),
    "get_profit_and_loss": Operation("Get Profit and Loss", "Reports", "GET", "/Reports/ProfitAndLoss",
                                     "accounting.reports.profitandloss.read"),
    "get_trial_balance": Operation("Get Trial Balance", "Reports", "GET", "/Reports/TrialBalance",
                                   "accounting.reports.trialbalance.read"),
    "list_projects": Operation("List Projects", "Projects", "GET", "/Projects", "projects.read", "projects"),
    "get_project": Operation("Get Project", "Projects", "GET", "/Projects/{projectId}",
                             "projects.read", "projects", required_fields=("projectId",)),
    "list_files": Operation("List Files", "Files", "GET", "/Files", "files.read", "files"),
    "list_folders": Operation("List Folders", "Files", "GET", "/Folders", "files.read", "files"),
    "list_assets": Operation("List Assets", "Assets", "GET", "/Assets", "assets.read", "assets",
                             required_fields=("status",)),
    "get_asset": Operation("Get Asset", "Assets", "GET", "/Assets/{id}", "assets.read", "assets",
                           required_fields=("id",)),
})
