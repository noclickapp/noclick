"""Stripe operation → OAuth scope requirements.

Stripe Connect's OAuth ``scope`` parameter takes exactly one of two values,
``read_write`` or ``read_only``, and Stripe documents ``read_only`` as usable
"only for extensions" — a Standard-account platform such as NoClick can only
ever mint ``read_write``. There is no per-resource scope vocabulary to mirror
here: one scope covers the whole API surface, so no operation in this node can
fail with a scope error the way Slack's could.

The table is therefore flat *by construction, not by omission*. What it buys is
inventory: every operation is named, so a newly added one cannot silently
inherit a coverage claim nobody checked. If Stripe ever gates a resource behind
something a connected-account token cannot hold, that operation gets its own
entry rather than defaulting in.

Two things this deliberately does NOT model:

- **Reads are declared ``read_write`` too.** They would run under ``read_only``,
  but the node never mints such a credential, and declaring a scope the connect
  request cannot contain would make the derived union a non-subset of the
  requested list for no real-world gain.
- **API-key credentials.** ``sk_``/``rk_`` keys carry no OAuth scopes. Restricted
  keys have their own per-resource permission model that Stripe does not express
  as scope strings, so it is out of this table's vocabulary entirely.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: The only scope a Standard-account Connect platform can request.
READ_WRITE = "read_write"

_RW = ScopeRequirement(scopes=(READ_WRITE,))

#: Every operation the node dispatches, including the per-event triggers (which
#: register a webhook endpoint — itself a write).
_OPERATIONS: tuple[str, ...] = (
    # -- Advanced ------------------------------------------------------
    "custom_request",
    # -- Apps ----------------------------------------------------------
    "delete_secret", "find_secret", "list_secrets", "set_secret",
    # -- Balance -------------------------------------------------------
    "list_balance_transactions", "retrieve_balance",
    "retrieve_balance_transaction",
    # -- Billing Alerts ------------------------------------------------
    "activate_alert", "archive_alert", "create_alert", "deactivate_alert",
    "list_alerts", "retrieve_alert",
    # -- Billing Credit ------------------------------------------------
    "create_credit_grant", "expire_credit_grant",
    "list_credit_balance_transactions", "list_credit_grants",
    "retrieve_credit_balance_summary", "retrieve_credit_balance_transaction",
    "retrieve_credit_grant", "update_credit_grant", "void_credit_grant",
    # -- Billing Meters ------------------------------------------------
    "create_meter", "create_meter_event", "create_meter_event_adjustment",
    "deactivate_meter", "list_meter_event_summaries", "list_meters",
    "reactivate_meter", "retrieve_meter", "update_meter",
    # -- Billing Portal ------------------------------------------------
    "create_billing_portal_session", "create_portal_configuration",
    "list_portal_configurations", "retrieve_portal_configuration",
    "update_portal_configuration",
    # -- Charges -------------------------------------------------------
    "capture_charge", "create_charge", "list_charges", "retrieve_charge",
    "search_charges", "update_charge",
    # -- Checkout ------------------------------------------------------
    "create_checkout_session", "expire_checkout_session",
    "list_checkout_line_items", "list_checkout_sessions",
    "retrieve_checkout_session",
    # -- Climate -------------------------------------------------------
    "cancel_climate_order", "create_climate_order", "list_climate_orders",
    "list_climate_products", "list_climate_suppliers",
    "retrieve_climate_order", "retrieve_climate_product",
    "retrieve_climate_supplier", "update_climate_order",
    # -- Connect -------------------------------------------------------
    "cancel_payout", "cancel_topup", "create_account", "create_account_link",
    "create_account_session", "create_application_fee_refund",
    "create_external_account", "create_login_link", "create_payout",
    "create_person", "create_topup", "create_transfer",
    "create_transfer_reversal", "delete_account", "delete_external_account",
    "delete_person", "list_accounts", "list_application_fee_refunds",
    "list_application_fees", "list_capabilities", "list_country_specs",
    "list_external_accounts", "list_payouts", "list_persons", "list_topups",
    "list_transfer_reversals", "list_transfers", "reject_account",
    "retrieve_account", "retrieve_application_fee",
    "retrieve_application_fee_refund", "retrieve_capability",
    "retrieve_country_spec", "retrieve_external_account", "retrieve_payout",
    "retrieve_person", "retrieve_topup", "retrieve_transfer",
    "retrieve_transfer_reversal", "reverse_payout", "update_account",
    "update_application_fee_refund", "update_capability",
    "update_external_account", "update_payout", "update_person",
    "update_transfer", "update_transfer_reversal",
    # -- Coupons -------------------------------------------------------
    "create_coupon", "delete_coupon", "list_coupons", "retrieve_coupon",
    "update_coupon",
    # -- Credit Notes --------------------------------------------------
    "create_credit_note", "list_credit_note_lines", "list_credit_notes",
    "preview_credit_note", "preview_credit_note_lines",
    "retrieve_credit_note", "update_credit_note", "void_credit_note",
    # -- Customers -----------------------------------------------------
    "create_customer", "create_customer_balance_transaction",
    "create_customer_session", "create_customer_tax_id", "delete_customer",
    "delete_customer_tax_id", "list_customer_balance_transactions",
    "list_customer_cash_balance_transactions", "list_customer_tax_ids",
    "list_customers", "retrieve_customer",
    "retrieve_customer_balance_transaction", "retrieve_customer_cash_balance",
    "retrieve_customer_cash_balance_transaction", "retrieve_customer_tax_id",
    "search_customers", "update_customer",
    "update_customer_balance_transaction", "update_customer_cash_balance",
    # -- Disputes ------------------------------------------------------
    "close_dispute", "list_disputes", "retrieve_dispute", "update_dispute",
    # -- Entitlements --------------------------------------------------
    "create_entitlements_feature", "list_active_entitlements",
    "list_entitlements_features", "retrieve_active_entitlement",
    "retrieve_entitlements_feature", "update_entitlements_feature",
    # -- Events --------------------------------------------------------
    "list_events", "retrieve_event",
    # -- Files ---------------------------------------------------------
    "create_file_link", "list_file_links", "list_files", "retrieve_file",
    "retrieve_file_link", "update_file_link",
    # -- Financial Connections -----------------------------------------
    "create_financial_connections_session",
    "disconnect_financial_connections_account",
    "list_financial_connections_account_owners",
    "list_financial_connections_accounts",
    "list_financial_connections_transactions",
    "refresh_financial_connections_account",
    "retrieve_financial_connections_account",
    "retrieve_financial_connections_session",
    "retrieve_financial_connections_transaction",
    "subscribe_financial_connections_account",
    "unsubscribe_financial_connections_account",
    # -- Forwarding ----------------------------------------------------
    "create_forwarding_request", "list_forwarding_requests",
    "retrieve_forwarding_request",
    # -- Identity ------------------------------------------------------
    "cancel_verification_session", "create_verification_session",
    "list_verification_reports", "list_verification_sessions",
    "redact_verification_session", "retrieve_verification_report",
    "retrieve_verification_session", "update_verification_session",
    # -- Invoice Items -------------------------------------------------
    "create_invoice_item", "delete_invoice_item", "list_invoice_items",
    "retrieve_invoice_item", "update_invoice_item",
    # -- Invoices ------------------------------------------------------
    "add_invoice_lines", "create_invoice", "create_preview_invoice",
    "delete_invoice", "finalize_invoice", "list_invoice_lines",
    "list_invoices", "mark_uncollectible_invoice", "pay_invoice",
    "remove_invoice_lines", "retrieve_invoice", "search_invoices",
    "send_invoice", "update_invoice", "update_invoice_line",
    "update_invoice_lines", "void_invoice",
    # -- Issuing -------------------------------------------------------
    "approve_issuing_authorization", "create_issuing_card",
    "create_issuing_cardholder", "create_issuing_dispute",
    "create_issuing_funding_instructions",
    "create_issuing_personalization_design", "decline_issuing_authorization",
    "list_issuing_authorizations", "list_issuing_cardholders",
    "list_issuing_cards", "list_issuing_disputes",
    "list_issuing_funding_instructions",
    "list_issuing_personalization_designs", "list_issuing_physical_bundles",
    "list_issuing_tokens", "list_issuing_transactions",
    "retrieve_issuing_authorization", "retrieve_issuing_card",
    "retrieve_issuing_cardholder", "retrieve_issuing_dispute",
    "retrieve_issuing_personalization_design",
    "retrieve_issuing_physical_bundle", "retrieve_issuing_token",
    "retrieve_issuing_transaction", "submit_issuing_dispute",
    "update_issuing_authorization", "update_issuing_card",
    "update_issuing_cardholder", "update_issuing_dispute",
    "update_issuing_personalization_design", "update_issuing_token",
    "update_issuing_transaction",
    # -- Payment Links -------------------------------------------------
    "create_payment_link", "list_payment_link_line_items",
    "list_payment_links", "retrieve_payment_link", "update_payment_link",
    # -- Payment Methods -----------------------------------------------
    "attach_payment_method", "create_payment_method",
    "create_payment_method_configuration", "create_payment_method_domain",
    "detach_payment_method", "list_payment_method_configurations",
    "list_payment_method_domains", "list_payment_methods",
    "retrieve_payment_method", "retrieve_payment_method_configuration",
    "retrieve_payment_method_domain", "update_payment_method",
    "update_payment_method_configuration", "update_payment_method_domain",
    "validate_payment_method_domain",
    # -- Payments ------------------------------------------------------
    "attach_source", "cancel_payment_intent", "capture_payment_intent",
    "confirm_payment_intent", "create_payment_intent", "create_source",
    "create_token", "detach_source", "list_payment_intents",
    "list_setup_attempts", "retrieve_confirmation_token", "retrieve_mandate",
    "retrieve_payment_intent", "retrieve_source", "retrieve_token",
    "search_payment_intents", "update_payment_intent", "update_source",
    # -- Prices --------------------------------------------------------
    "create_price", "list_prices", "retrieve_price", "search_prices",
    "update_price",
    # -- Products ------------------------------------------------------
    "create_product", "delete_product", "list_products", "retrieve_product",
    "search_products", "update_product",
    # -- Promotion Codes -----------------------------------------------
    "create_promotion_code", "list_promotion_codes",
    "retrieve_promotion_code", "update_promotion_code",
    # -- Quotes --------------------------------------------------------
    "accept_quote", "cancel_quote", "create_quote", "finalize_quote",
    "list_quote_computed_upfront_line_items", "list_quote_line_items",
    "list_quotes", "retrieve_quote", "update_quote",
    # -- Radar ---------------------------------------------------------
    "approve_review", "create_value_list", "create_value_list_item",
    "delete_value_list", "delete_value_list_item",
    "list_early_fraud_warnings", "list_reviews", "list_value_list_items",
    "list_value_lists", "retrieve_early_fraud_warning", "retrieve_review",
    "retrieve_value_list", "retrieve_value_list_item", "update_value_list",
    # -- Refunds -------------------------------------------------------
    "cancel_refund", "create_refund", "list_refunds", "retrieve_refund",
    "update_refund",
    # -- Reporting -----------------------------------------------------
    "create_report_run", "list_report_runs", "list_report_types",
    "list_scheduled_query_runs", "retrieve_report_run",
    "retrieve_report_type", "retrieve_scheduled_query_run",
    # -- Setup Intents -------------------------------------------------
    "cancel_setup_intent", "confirm_setup_intent", "create_setup_intent",
    "list_setup_intents", "retrieve_setup_intent", "update_setup_intent",
    # -- Shipping Rates ------------------------------------------------
    "create_shipping_rate", "list_shipping_rates", "retrieve_shipping_rate",
    "update_shipping_rate",
    # -- Subscription Items --------------------------------------------
    "create_subscription_item", "create_usage_record",
    "delete_subscription_item", "list_subscription_items",
    "list_usage_record_summaries", "retrieve_subscription_item",
    "update_subscription_item",
    # -- Subscription Schedules ----------------------------------------
    "cancel_subscription_schedule", "create_subscription_schedule",
    "list_subscription_schedules", "release_subscription_schedule",
    "retrieve_subscription_schedule", "update_subscription_schedule",
    # -- Subscriptions -------------------------------------------------
    "cancel_subscription", "create_subscription", "list_subscriptions",
    "resume_subscription", "retrieve_subscription", "search_subscriptions",
    "update_subscription",
    # -- Tax -----------------------------------------------------------
    "create_tax_calculation", "create_tax_id", "create_tax_registration",
    "create_tax_transaction_from_calculation",
    "create_tax_transaction_reversal", "delete_tax_id",
    "list_tax_calculation_line_items", "list_tax_codes", "list_tax_ids",
    "list_tax_registrations", "list_tax_transaction_line_items",
    "retrieve_tax_calculation", "retrieve_tax_code", "retrieve_tax_id",
    "retrieve_tax_registration", "retrieve_tax_settings",
    "retrieve_tax_transaction", "update_tax_registration",
    "update_tax_settings",
    # -- Tax Rates -----------------------------------------------------
    "create_tax_rate", "list_tax_rates", "retrieve_tax_rate",
    "update_tax_rate",
    # -- Terminal ------------------------------------------------------
    "cancel_action_terminal_reader", "collect_inputs_terminal_reader",
    "create_terminal_configuration", "create_terminal_connection_token",
    "create_terminal_location", "create_terminal_reader",
    "delete_terminal_configuration", "delete_terminal_location",
    "delete_terminal_reader", "list_terminal_configurations",
    "list_terminal_locations", "list_terminal_readers",
    "process_payment_intent_terminal_reader",
    "process_setup_intent_terminal_reader", "refund_payment_terminal_reader",
    "retrieve_terminal_configuration", "retrieve_terminal_location",
    "retrieve_terminal_reader", "update_terminal_configuration",
    "update_terminal_location", "update_terminal_reader",
    # -- Test Helpers --------------------------------------------------
    "advance_test_clock", "create_test_clock", "delete_test_clock",
    "list_test_clocks", "retrieve_test_clock",
    # -- Treasury ------------------------------------------------------
    "cancel_treasury_inbound_transfer", "cancel_treasury_outbound_payment",
    "cancel_treasury_outbound_transfer", "create_treasury_credit_reversal",
    "create_treasury_debit_reversal", "create_treasury_financial_account",
    "create_treasury_inbound_transfer", "create_treasury_outbound_payment",
    "create_treasury_outbound_transfer", "list_treasury_credit_reversals",
    "list_treasury_debit_reversals", "list_treasury_financial_accounts",
    "list_treasury_inbound_transfers", "list_treasury_outbound_payments",
    "list_treasury_outbound_transfers", "list_treasury_received_credits",
    "list_treasury_received_debits", "list_treasury_transaction_entries",
    "list_treasury_transactions", "retrieve_treasury_credit_reversal",
    "retrieve_treasury_debit_reversal", "retrieve_treasury_financial_account",
    "retrieve_treasury_financial_account_features",
    "retrieve_treasury_inbound_transfer",
    "retrieve_treasury_outbound_payment",
    "retrieve_treasury_outbound_transfer",
    "retrieve_treasury_received_credit", "retrieve_treasury_received_debit",
    "retrieve_treasury_transaction", "retrieve_treasury_transaction_entry",
    "update_treasury_financial_account",
    "update_treasury_financial_account_features",
    # -- Triggers ------------------------------------------------------
    "on_account_application_deauthorized", "on_account_updated",
    "on_charge_captured", "on_charge_dispute_closed",
    "on_charge_dispute_created", "on_charge_dispute_funds_withdrawn",
    "on_charge_dispute_updated", "on_charge_failed",
    "on_charge_refund_updated", "on_charge_refunded", "on_charge_succeeded",
    "on_charge_updated", "on_checkout_session_async_payment_failed",
    "on_checkout_session_async_payment_succeeded",
    "on_checkout_session_completed", "on_checkout_session_expired",
    "on_customer_created", "on_customer_deleted",
    "on_customer_subscription_created", "on_customer_subscription_deleted",
    "on_customer_subscription_paused", "on_customer_subscription_resumed",
    "on_customer_subscription_trial_will_end",
    "on_customer_subscription_updated", "on_customer_updated", "on_event",
    "on_invoice_created", "on_invoice_finalized",
    "on_invoice_marked_uncollectible", "on_invoice_paid",
    "on_invoice_payment_action_required", "on_invoice_payment_failed",
    "on_invoice_payment_succeeded", "on_invoice_upcoming",
    "on_invoice_voided", "on_payment_intent_canceled",
    "on_payment_intent_created", "on_payment_intent_payment_failed",
    "on_payment_intent_processing", "on_payment_intent_requires_action",
    "on_payment_intent_succeeded", "on_payment_method_attached",
    "on_payment_method_detached", "on_payout_created", "on_payout_failed",
    "on_payout_paid", "on_price_created", "on_price_updated",
    "on_product_created", "on_product_deleted", "on_product_updated",
    "on_quote_accepted", "on_review_closed", "on_review_opened",
    "on_setup_intent_setup_failed", "on_setup_intent_succeeded",
    # -- Webhooks ------------------------------------------------------
    "create_webhook_endpoint", "delete_webhook_endpoint",
    "list_webhook_endpoints", "retrieve_webhook_endpoint",
    "update_webhook_endpoint",
)

_REQUIREMENTS: dict[str, ScopeRequirement] = {op: _RW for op in _OPERATIONS}

STRIPE_SCOPES = ScopeRegistry(
    provider="stripe",
    requirements=_REQUIREMENTS,
)
