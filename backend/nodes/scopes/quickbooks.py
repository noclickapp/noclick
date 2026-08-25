"""QuickBooks (Intuit) operation → OAuth scope requirements.

Intuit's scopes are coarse: one per product API, not per endpoint. Everything
this node does lives in exactly two of them.

- ``com.intuit.quickbooks.accounting`` — the Accounting API
  (``/v3/company/{realmId}/...``). That is every entity operation, ``run_query``,
  ``batch``, reports, the invoice PDF/send endpoints, and the accounting custom
  request. It is also the scope a connection must hold to RECEIVE QuickBooks
  Online webhook notifications, so the generated ``on_<entity>_<event>``
  triggers declare it too — no endpoint call implies it, but without it the
  events never arrive.
- ``com.intuit.quickbooks.payment`` — the Payments API
  (``https://api.intuit.com/quickbooks/v4/payments``). Only
  ``execute_custom_payments_rest_request`` routes there. Note that the
  ``Payment`` entity operations are NOT this scope: a QuickBooks ``Payment`` is
  an accounting record of a customer payment against an invoice, and those
  handlers hit the accounting host.

``openid``/``profile``/``email`` are also requested. They back the OpenID
Connect identity used to label the credential, not any operation, so nothing in
this table declares them — ``SUBSET`` enforcement is what keeps them legal.

Intuit rejects the entire authorization with ``invalid_scope`` if a requested
scope is not enabled on the app, so the requested list is pinned to what the
shared NoClick app is provisioned for. Never widen it from here.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: The Accounting API, and the scope a connection needs to receive QuickBooks
#: Online webhook notifications.
_ACCOUNTING = ScopeRequirement(scopes=("com.intuit.quickbooks.accounting",))

#: The Payments API host, which is a different product with a different scope.
_PAYMENTS = ScopeRequirement(scopes=("com.intuit.quickbooks.payment",))

_ACCOUNTING_OPERATIONS: tuple[str, ...] = (
    "batch",
    "create_account",
    "create_bill",
    "create_bill_payment",
    "create_credit_memo",
    "create_customer",
    "create_estimate",
    "create_invoice",
    "create_item",
    "create_journal_entry",
    "create_payment",
    "create_purchase",
    "create_purchase_order",
    "create_sales_receipt",
    "create_vendor",
    "delete_bill",
    "delete_invoice",
    "execute_custom_accounting_rest_request",
    "get_company_info",
    "get_invoice_pdf",
    "get_report",
    "on_account_create",
    "on_account_delete",
    "on_account_merge",
    "on_account_update",
    "on_bill_create",
    "on_bill_delete",
    "on_bill_update",
    "on_bill_void",
    "on_billpayment_create",
    "on_billpayment_delete",
    "on_billpayment_update",
    "on_billpayment_void",
    "on_budget_create",
    "on_budget_delete",
    "on_budget_update",
    "on_class_create",
    "on_class_delete",
    "on_class_merge",
    "on_class_update",
    "on_creditmemo_create",
    "on_creditmemo_delete",
    "on_creditmemo_update",
    "on_creditmemo_void",
    "on_currency_create",
    "on_currency_delete",
    "on_currency_update",
    "on_customer_create",
    "on_customer_delete",
    "on_customer_merge",
    "on_customer_update",
    "on_department_create",
    "on_department_delete",
    "on_department_merge",
    "on_department_update",
    "on_deposit_create",
    "on_deposit_delete",
    "on_deposit_update",
    "on_deposit_void",
    "on_employee_create",
    "on_employee_delete",
    "on_employee_merge",
    "on_employee_update",
    "on_estimate_create",
    "on_estimate_delete",
    "on_estimate_emailed",
    "on_estimate_update",
    "on_estimate_void",
    "on_invoice_create",
    "on_invoice_delete",
    "on_invoice_emailed",
    "on_invoice_update",
    "on_invoice_void",
    "on_item_create",
    "on_item_delete",
    "on_item_merge",
    "on_item_update",
    "on_journalcode_create",
    "on_journalcode_delete",
    "on_journalcode_update",
    "on_journalentry_create",
    "on_journalentry_delete",
    "on_journalentry_update",
    "on_journalentry_void",
    "on_payment_create",
    "on_payment_delete",
    "on_payment_update",
    "on_payment_void",
    "on_paymentmethod_create",
    "on_paymentmethod_delete",
    "on_paymentmethod_merge",
    "on_paymentmethod_update",
    "on_preferences_create",
    "on_preferences_delete",
    "on_preferences_update",
    "on_purchase_create",
    "on_purchase_delete",
    "on_purchase_update",
    "on_purchase_void",
    "on_purchaseorder_create",
    "on_purchaseorder_delete",
    "on_purchaseorder_update",
    "on_purchaseorder_void",
    "on_refundreceipt_create",
    "on_refundreceipt_delete",
    "on_refundreceipt_update",
    "on_refundreceipt_void",
    "on_salesreceipt_create",
    "on_salesreceipt_delete",
    "on_salesreceipt_update",
    "on_salesreceipt_void",
    "on_taxagency_create",
    "on_taxagency_delete",
    "on_taxagency_merge",
    "on_taxagency_update",
    "on_term_create",
    "on_term_delete",
    "on_term_merge",
    "on_term_update",
    "on_timeactivity_create",
    "on_timeactivity_delete",
    "on_timeactivity_update",
    "on_transfer_create",
    "on_transfer_delete",
    "on_transfer_update",
    "on_transfer_void",
    "on_vendor_create",
    "on_vendor_delete",
    "on_vendor_merge",
    "on_vendor_update",
    "on_vendorcredit_create",
    "on_vendorcredit_delete",
    "on_vendorcredit_update",
    "on_vendorcredit_void",
    "read_account",
    "read_bill",
    "read_customer",
    "read_invoice",
    "read_item",
    "read_payment",
    "read_vendor",
    "run_query",
    "send_invoice",
    "update_account",
    "update_bill",
    "update_customer",
    "update_invoice",
    "update_item",
    "update_payment",
    "update_vendor",
)

_REQUIREMENTS: dict[str, ScopeRequirement] = {
    operation: _ACCOUNTING for operation in _ACCOUNTING_OPERATIONS
}


QUICKBOOKS_SCOPES = ScopeRegistry(
    provider="quickbooks",
    requirements=_REQUIREMENTS,
    unmapped=(
        # The shared NoClick app is Accounting-only — the Payments API scope
        # (com.intuit.quickbooks.payment) is no longer requested, so the one op
        # that routes to the Payments host can't be satisfied. Kept selectable
        # for a bring-your-own-app credential that holds the scope, but
        # unmapped here so the request list stays accounting-only.
        "execute_custom_payments_rest_request",
        # PayrollEmployee and Payslips are QuickBooks Payroll entities,
        # documented under Intuit's separate payroll-time product, not the
        # Accounting API. Intuit publishes no scope string for payroll webhook
        # delivery, so mapping these to the accounting scope would be a guess.
        # If these triggers are found not to fire, the payroll scope is the
        # first thing to check.
        "on_payrollemployee_create",
        "on_payrollemployee_delete",
        "on_payrollemployee_update",
        "on_payslips_create",
        "on_payslips_delete",
        "on_payslips_update",
    ),
)
