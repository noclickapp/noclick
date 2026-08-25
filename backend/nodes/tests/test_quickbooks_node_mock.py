"""
Mock tests for the QuickBooks Online (Intuit Accounting API) node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Query, Invoices (create/read/update/delete/send/pdf), Customers, Vendors,
  Bills, Payments, Bill payments, Estimates, Sales receipts, Credit memos,
  Items, Accounts, Purchases, Journal entries, Purchase orders, Reports,
  Batch, Company info
- Triggers: per-(entity, operation) webhook passthrough + entity/op filtering +
  intuit-signature verification
- Error handling: API errors, missing credentials
- Dynamic options: customer dropdown

OAuth token refresh is patched out (QuickBooksNode._get_access_token) so tests
run without a database — the node's HTTP layer is what's under test.
"""

import base64
import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.quickbooks_node import (
    QuickBooksNode,
    QuickBooksNodeConfig,
    QuickBooksOAuthCredential,
    QuickBooksRunQueryConfig,
    QuickBooksCreateInvoiceConfig,
    QuickBooksReadInvoiceConfig,
    QuickBooksUpdateInvoiceConfig,
    QuickBooksDeleteInvoiceConfig,
    QuickBooksSendInvoiceConfig,
    QuickBooksGetInvoicePdfConfig,
    QuickBooksCreateCustomerConfig,
    QuickBooksReadCustomerConfig,
    QuickBooksUpdateCustomerConfig,
    QuickBooksCreateVendorConfig,
    QuickBooksReadVendorConfig,
    QuickBooksUpdateVendorConfig,
    QuickBooksCreateBillConfig,
    QuickBooksReadBillConfig,
    QuickBooksUpdateBillConfig,
    QuickBooksDeleteBillConfig,
    QuickBooksCreatePaymentConfig,
    QuickBooksReadPaymentConfig,
    QuickBooksUpdatePaymentConfig,
    QuickBooksCreateBillPaymentConfig,
    QuickBooksCreateEstimateConfig,
    QuickBooksCreateSalesReceiptConfig,
    QuickBooksCreateCreditMemoConfig,
    QuickBooksCreateItemConfig,
    QuickBooksReadItemConfig,
    QuickBooksUpdateItemConfig,
    QuickBooksCreateAccountConfig,
    QuickBooksReadAccountConfig,
    QuickBooksUpdateAccountConfig,
    QuickBooksCreatePurchaseConfig,
    QuickBooksCreateJournalEntryConfig,
    QuickBooksCreatePurchaseOrderConfig,
    QuickBooksGetReportConfig,
    QuickBooksBatchConfig,
    QuickBooksGetCompanyInfoConfig,
    QuickBooksCustomAccountingRestRequestConfig,
)


@pytest.fixture
def oauth_credentials():
    return QuickBooksOAuthCredential(
        access_token="qb_access_token",
        refresh_token="qb_refresh_token",
        expires_at="2999-01-01T00:00:00+00:00",
        realm_id="1234567890",
        is_sandbox=True,
    )


def create_quickbooks_node(config):
    return QuickBooksNode(
        node_id="test-quickbooks-node",
        node_type="automation-quickbooks",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, content=b""):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.content = content if content else b'{"ok": true}'
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, content=b""):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, content)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def create_capture_mock_client(status_code=200, json_data=None, content=b""):
    """Mock httpx.AsyncClient and capture request call kwargs for assertions."""
    mock_response = create_mock_response(status_code, json_data, content)
    mock_client = Mock()
    captured = {}

    async def async_request(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return mock_response

    async def async_post(*args, **kwargs):
        captured["post_args"] = args
        captured["post_kwargs"] = kwargs
        return mock_response

    mock_client.request = async_request
    mock_client.post = async_post

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client, captured


async def _run(node, status_code=200, json_data=None, content=b""):
    """Execute a node with a mocked HTTP client and a stubbed OAuth token."""
    mock_client = create_mock_client(status_code, json_data, content)
    with patch(
        "nodes.quickbooks_node.QuickBooksNode._get_access_token",
        return_value="qb_access_token",
    ), patch(
        "nodes.quickbooks_node.httpx.AsyncClient", return_value=mock_client
    ):
        return await node.execute({})


class TestQuickBooksQueryMock:
    @pytest.mark.asyncio
    async def test_run_query(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksRunQueryConfig(query="SELECT * FROM Invoice MAXRESULTS 10"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(
            node, 200, {"QueryResponse": {"Invoice": [{"Id": "1"}, {"Id": "2"}]}}
        )
        assert result["status"] == "success"
        assert result["action"] == "run_query"
        assert len(result["data"]["QueryResponse"]["Invoice"]) == 2


class TestQuickBooksInvoicesMock:
    @pytest.mark.asyncio
    async def test_create_invoice(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateInvoiceConfig(
                customer_id="12",
                line='[{"Amount":100,"DetailType":"SalesItemLineDetail","SalesItemLineDetail":{"ItemRef":{"value":"1"}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Invoice": {"Id": "55", "TotalAmt": 100}})
        assert result["status"] == "success"
        assert result["action"] == "create_invoice"
        assert result["data"]["Invoice"]["Id"] == "55"

    @pytest.mark.asyncio
    async def test_read_invoice(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksReadInvoiceConfig(invoice_id="55"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Invoice": {"Id": "55"}})
        assert result["status"] == "success"
        assert result["action"] == "read_invoice"

    @pytest.mark.asyncio
    async def test_update_invoice(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksUpdateInvoiceConfig(
                invoice_id="55", sync_token="2", fields='{"CustomerMemo":{"value":"Thanks"}}'
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Invoice": {"Id": "55", "SyncToken": "3"}})
        assert result["status"] == "success"
        assert result["action"] == "update_invoice"

    @pytest.mark.asyncio
    async def test_delete_invoice(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksDeleteInvoiceConfig(invoice_id="55", sync_token="3"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Invoice": {"status": "Deleted"}})
        assert result["status"] == "success"
        assert result["action"] == "delete_invoice"

    @pytest.mark.asyncio
    async def test_send_invoice(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksSendInvoiceConfig(invoice_id="55", send_to="a@example.com"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Invoice": {"Id": "55"}})
        assert result["status"] == "success"
        assert result["action"] == "send_invoice"

    @pytest.mark.asyncio
    async def test_get_invoice_pdf(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksGetInvoicePdfConfig(invoice_id="55"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, content=b"%PDF-1.4 fake")
        assert result["status"] == "success"
        assert result["action"] == "get_invoice_pdf"
        # PDF bytes come back as a BinaryOutput marker (executor resolves it to a
        # file URL); never base64-encoded inline.
        from nodes.core.binary_output import BinaryOutput
        assert isinstance(result["data"], BinaryOutput)
        assert result["data"].data == b"%PDF-1.4 fake"
        assert result["data"].content_type == "application/pdf"
        assert result["data"].filename == "get_invoice_pdf.pdf"


class TestQuickBooksCustomersMock:
    @pytest.mark.asyncio
    async def test_create_customer(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateCustomerConfig(
                display_name="Acme Inc", email="ar@acme.com", company_name="Acme"
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Customer": {"Id": "9"}})
        assert result["status"] == "success"
        assert result["action"] == "create_customer"

    @pytest.mark.asyncio
    async def test_read_customer(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksReadCustomerConfig(customer_id="9"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Customer": {"Id": "9"}})
        assert result["status"] == "success"
        assert result["action"] == "read_customer"

    @pytest.mark.asyncio
    async def test_update_customer(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksUpdateCustomerConfig(
                customer_id="9", sync_token="0", fields='{"PrimaryEmailAddr":{"Address":"new@acme.com"}}'
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Customer": {"Id": "9", "SyncToken": "1"}})
        assert result["status"] == "success"
        assert result["action"] == "update_customer"


class TestQuickBooksVendorsMock:
    @pytest.mark.asyncio
    async def test_create_vendor(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateVendorConfig(display_name="Supplier LLC"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Vendor": {"Id": "20"}})
        assert result["status"] == "success"
        assert result["action"] == "create_vendor"

    @pytest.mark.asyncio
    async def test_read_vendor(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksReadVendorConfig(vendor_id="20"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Vendor": {"Id": "20"}})
        assert result["status"] == "success"
        assert result["action"] == "read_vendor"

    @pytest.mark.asyncio
    async def test_update_vendor(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksUpdateVendorConfig(
                vendor_id="20", sync_token="0", fields='{"CompanyName":"Supplier LLC"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Vendor": {"Id": "20"}})
        assert result["status"] == "success"
        assert result["action"] == "update_vendor"


class TestQuickBooksBillsMock:
    @pytest.mark.asyncio
    async def test_create_bill(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateBillConfig(
                vendor_id="20",
                line='[{"Amount":50,"DetailType":"AccountBasedExpenseLineDetail","AccountBasedExpenseLineDetail":{"AccountRef":{"value":"7"}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Bill": {"Id": "30"}})
        assert result["status"] == "success"
        assert result["action"] == "create_bill"

    @pytest.mark.asyncio
    async def test_read_bill(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksReadBillConfig(bill_id="30"), credentials=oauth_credentials
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Bill": {"Id": "30"}})
        assert result["status"] == "success"
        assert result["action"] == "read_bill"

    @pytest.mark.asyncio
    async def test_update_bill(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksUpdateBillConfig(
                bill_id="30", sync_token="0", fields='{"PrivateNote":"updated"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Bill": {"Id": "30"}})
        assert result["status"] == "success"
        assert result["action"] == "update_bill"

    @pytest.mark.asyncio
    async def test_delete_bill(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksDeleteBillConfig(bill_id="30", sync_token="1"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Bill": {"status": "Deleted"}})
        assert result["status"] == "success"
        assert result["action"] == "delete_bill"


class TestQuickBooksPaymentsMock:
    @pytest.mark.asyncio
    async def test_create_payment(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreatePaymentConfig(
                customer_id="9", total_amount="100.00",
                line='[{"Amount":100,"LinkedTxn":[{"TxnId":"55","TxnType":"Invoice"}]}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Payment": {"Id": "40"}})
        assert result["status"] == "success"
        assert result["action"] == "create_payment"

    @pytest.mark.asyncio
    async def test_read_payment(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksReadPaymentConfig(payment_id="40"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Payment": {"Id": "40"}})
        assert result["status"] == "success"
        assert result["action"] == "read_payment"

    @pytest.mark.asyncio
    async def test_update_payment(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksUpdatePaymentConfig(
                payment_id="40", sync_token="0", fields='{"PrivateNote":"note"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Payment": {"Id": "40"}})
        assert result["status"] == "success"
        assert result["action"] == "update_payment"

    @pytest.mark.asyncio
    async def test_create_bill_payment(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateBillPaymentConfig(
                vendor_id="20", total_amount="50.00", pay_type="Check", account_id="35",
                line='[{"Amount":50,"LinkedTxn":[{"TxnId":"30","TxnType":"Bill"}]}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        mock_client, captured = create_capture_mock_client(200, {"BillPayment": {"Id": "45"}})
        with patch(
            "nodes.quickbooks_node.QuickBooksNode._get_access_token",
            return_value="qb_access_token",
        ), patch("nodes.quickbooks_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_bill_payment"
        # QuickBooks rejects a Check bill payment without CheckPayment.BankAccountRef.
        body = captured["kwargs"]["json"]
        assert body["CheckPayment"]["BankAccountRef"]["value"] == "35"

    @pytest.mark.asyncio
    async def test_create_bill_payment_credit_card(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateBillPaymentConfig(
                vendor_id="20", total_amount="50.00", pay_type="CreditCard", account_id="41",
                line='[{"Amount":50,"LinkedTxn":[{"TxnId":"30","TxnType":"Bill"}]}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        mock_client, captured = create_capture_mock_client(200, {"BillPayment": {"Id": "46"}})
        with patch(
            "nodes.quickbooks_node.QuickBooksNode._get_access_token",
            return_value="qb_access_token",
        ), patch("nodes.quickbooks_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        body = captured["kwargs"]["json"]
        assert body["CreditCardPayment"]["CCAccountRef"]["value"] == "41"


class TestQuickBooksSalesMock:
    @pytest.mark.asyncio
    async def test_create_estimate(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateEstimateConfig(
                customer_id="9",
                line='[{"Amount":200,"DetailType":"SalesItemLineDetail","SalesItemLineDetail":{"ItemRef":{"value":"1"}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Estimate": {"Id": "60"}})
        assert result["status"] == "success"
        assert result["action"] == "create_estimate"

    @pytest.mark.asyncio
    async def test_create_sales_receipt(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateSalesReceiptConfig(
                customer_id="9",
                line='[{"Amount":75,"DetailType":"SalesItemLineDetail","SalesItemLineDetail":{"ItemRef":{"value":"1"}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"SalesReceipt": {"Id": "61"}})
        assert result["status"] == "success"
        assert result["action"] == "create_sales_receipt"

    @pytest.mark.asyncio
    async def test_create_credit_memo(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateCreditMemoConfig(
                customer_id="9",
                line='[{"Amount":25,"DetailType":"SalesItemLineDetail","SalesItemLineDetail":{"ItemRef":{"value":"1"}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"CreditMemo": {"Id": "62"}})
        assert result["status"] == "success"
        assert result["action"] == "create_credit_memo"


class TestQuickBooksListsMock:
    @pytest.mark.asyncio
    async def test_create_item(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateItemConfig(
                name="Consulting", item_type="Service", income_account_id="79", unit_price="150"
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Item": {"Id": "70"}})
        assert result["status"] == "success"
        assert result["action"] == "create_item"

    @pytest.mark.asyncio
    async def test_read_item(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksReadItemConfig(item_id="70"), credentials=oauth_credentials
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Item": {"Id": "70"}})
        assert result["status"] == "success"
        assert result["action"] == "read_item"

    @pytest.mark.asyncio
    async def test_update_item(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksUpdateItemConfig(
                item_id="70", sync_token="0", fields='{"UnitPrice":175}'
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Item": {"Id": "70"}})
        assert result["status"] == "success"
        assert result["action"] == "update_item"

    @pytest.mark.asyncio
    async def test_create_account(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateAccountConfig(name="Marketing", account_type="Expense"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Account": {"Id": "80"}})
        assert result["status"] == "success"
        assert result["action"] == "create_account"

    @pytest.mark.asyncio
    async def test_read_account(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksReadAccountConfig(account_id="80"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Account": {"Id": "80"}})
        assert result["status"] == "success"
        assert result["action"] == "read_account"

    @pytest.mark.asyncio
    async def test_update_account(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksUpdateAccountConfig(
                account_id="80", sync_token="0", fields='{"Name":"Marketing & Ads"}'
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Account": {"Id": "80"}})
        assert result["status"] == "success"
        assert result["action"] == "update_account"


class TestQuickBooksExpensesMock:
    @pytest.mark.asyncio
    async def test_create_purchase(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreatePurchaseConfig(
                account_id="35", payment_type="Cash",
                line='[{"Amount":40,"DetailType":"AccountBasedExpenseLineDetail","AccountBasedExpenseLineDetail":{"AccountRef":{"value":"7"}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Purchase": {"Id": "90"}})
        assert result["status"] == "success"
        assert result["action"] == "create_purchase"

    @pytest.mark.asyncio
    async def test_create_journal_entry(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreateJournalEntryConfig(
                line='[{"Amount":100,"DetailType":"JournalEntryLineDetail","JournalEntryLineDetail":{"PostingType":"Debit","AccountRef":{"value":"7"}}},{"Amount":100,"DetailType":"JournalEntryLineDetail","JournalEntryLineDetail":{"PostingType":"Credit","AccountRef":{"value":"8"}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"JournalEntry": {"Id": "91"}})
        assert result["status"] == "success"
        assert result["action"] == "create_journal_entry"

    @pytest.mark.asyncio
    async def test_create_purchase_order(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCreatePurchaseOrderConfig(
                vendor_id="20", ap_account_id="33",
                line='[{"Amount":60,"DetailType":"ItemBasedExpenseLineDetail","ItemBasedExpenseLineDetail":{"ItemRef":{"value":"1"}}}]',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"PurchaseOrder": {"Id": "92"}})
        assert result["status"] == "success"
        assert result["action"] == "create_purchase_order"


class TestQuickBooksReportsMock:
    @pytest.mark.asyncio
    async def test_get_report(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksGetReportConfig(
                report_name="ProfitAndLoss", start_date="2026-01-01", end_date="2026-01-31"
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"Header": {"ReportName": "ProfitAndLoss"}})
        assert result["status"] == "success"
        assert result["action"] == "get_report"
        assert result["data"]["Header"]["ReportName"] == "ProfitAndLoss"


class TestQuickBooksAdvancedMock:
    @pytest.mark.asyncio
    async def test_batch(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksBatchConfig(
                batch_item_request='[{"bId":"1","Query":"SELECT * FROM Customer"}]'
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"BatchItemResponse": [{"bId": "1"}]})
        assert result["status"] == "success"
        assert result["action"] == "batch"

    @pytest.mark.asyncio
    async def test_get_company_info(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksGetCompanyInfoConfig(), credentials=oauth_credentials
        )
        node = create_quickbooks_node(config)
        result = await _run(node, 200, {"CompanyInfo": {"CompanyName": "Acme"}})
        assert result["status"] == "success"
        assert result["action"] == "get_company_info"
        assert result["data"]["CompanyInfo"]["CompanyName"] == "Acme"

    @pytest.mark.asyncio
    async def test_custom_accounting_rest_request(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksCustomAccountingRestRequestConfig(
                method="POST",
                endpoint="/customer",
                query_params='{"include":"all"}',
                body='{"DisplayName":"Acme Custom"}',
            ),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        mock_client, captured = create_capture_mock_client(200, {"Customer": {"Id": "42"}})
        with patch(
            "nodes.quickbooks_node.QuickBooksNode._get_access_token",
            return_value="qb_access_token",
        ), patch("nodes.quickbooks_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "execute_custom_accounting_rest_request"
        assert captured["kwargs"]["method"] == "POST"
        assert captured["kwargs"]["url"].endswith("/1234567890/customer")
        assert captured["kwargs"]["params"]["include"] == "all"
        assert captured["kwargs"]["params"]["minorversion"] == "75"
        assert captured["kwargs"]["json"] == {"DisplayName": "Acme Custom"}

    def test_credential_requests_all_scopes_upfront(self):
        """Scopes are requested together at connect time (like a standard OAuth
        app) — no per-scope picker. Only app-provisioned scopes are requested
        (accounting + OpenID); requesting an unapproved scope makes Intuit reject
        the whole authorization with invalid_scope. The Payments scope is NOT
        requested — the Payments API surface was removed."""
        schema = QuickBooksOAuthCredential.model_json_schema()
        assert schema["x-oauth-provider"] == "quickbooks"
        assert "x-oauth-optional-scopes" not in schema
        scopes = set(schema.get("x-oauth-scopes") or [])
        assert "com.intuit.quickbooks.accounting" in scopes
        assert "com.intuit.quickbooks.payment" not in scopes
        assert "openid" in scopes
        # premium GraphQL scopes are NOT requested (app isn't provisioned for them)
        assert "project-management.project" not in scopes


def _trigger_config(operation, **kw):
    """Build a QuickBooksNodeConfig for a generated per-(entity, operation)
    trigger via its discriminator string (e.g. 'on_invoice_create')."""
    return QuickBooksNodeConfig(
        config={"operation": operation, **kw}, credentials=None
    )


class TestQuickBooksTriggerMock:
    @pytest.mark.asyncio
    async def test_receive_webhook_passthrough(self):
        """The trigger passes the inbound webhook payload through, tagged with
        its own (entity, operation) discriminator as the action."""
        node = create_quickbooks_node(
            _trigger_config("on_invoice_create", webhook_url="https://abc.hooks.example.test")
        )
        payload = {
            "eventNotifications": [
                {"realmId": "123", "dataChangeEvent": {"entities": [{"name": "Invoice", "operation": "Create"}]}}
            ]
        }
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_invoice_create"
        assert result["data"]["eventNotifications"][0]["realmId"] == "123"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    def test_verify_webhook_signature(self):
        secret = "verifier_token"
        body = b'{"eventNotifications":[]}'
        digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        good_sig = base64.b64encode(digest).decode()
        assert QuickBooksNode.verify_webhook_signature(
            body, {"intuit-signature": good_sig}, {"signing_secret": secret}
        )
        assert not QuickBooksNode.verify_webhook_signature(
            body, {"intuit-signature": "ZGVhZGJlZWY="}, {"signing_secret": secret}
        )
        # no verifier token stored yet -> accept (trigger not armed)
        assert QuickBooksNode.verify_webhook_signature(body, {}, {})


def _qb_payload(*names, operation="Update"):
    """Build a QuickBooks eventNotifications payload changing the given entities."""
    return {
        "eventNotifications": [
            {
                "realmId": "123",
                "dataChangeEvent": {
                    "entities": [
                        {"name": name, "id": "1", "operation": operation} for name in names
                    ]
                },
            }
        ]
    }


def _qb_cloudevents_payload(*events, operation="updated"):
    """Build the current docs-style QuickBooks webhook payload."""
    payload = []
    for entity_name, realm_id in events:
        payload.append(
            {
                "specversion": "1.0",
                "id": f"{entity_name.lower()}-{realm_id}",
                "source": "test",
                "type": f"com.intuit.qbo.{entity_name.lower()}.{operation}.v1",
                "datacontenttype": "application/json",
                "time": "2026-07-09T00:00:00Z",
                "intuitentityid": "1",
                "intuitaccountid": str(realm_id),
                "data": {},
            }
        )
    return payload


class TestQuickBooksTriggerEventFilter:
    """Each generated trigger fires only for its own (entity, operation), since
    QuickBooks delivers every subscribed entity+event to one URL with no
    per-subscription filter."""

    def test_matching_entity_and_operation_passes(self):
        payload = _qb_payload("Invoice", operation="Update")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "on_invoice_update"}) is True

    def test_wrong_entity_skipped(self):
        payload = _qb_payload("Customer", operation="Update")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "on_invoice_update"}) is False

    def test_wrong_operation_skipped(self):
        """Invoice Created delivery must NOT fire the Invoice Updated trigger."""
        payload = _qb_payload("Invoice", operation="Create")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "on_invoice_update"}) is False

    def test_unknown_operation_fails_open(self):
        """An unrecognized trigger operation processes the delivery (fail-open)."""
        payload = _qb_payload("Invoice", operation="Update")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "bogus"}) is True

    def test_case_insensitive_entity_and_op_match(self):
        payload = _qb_payload("invoice", operation="update")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "on_invoice_update"}) is True

    def test_multi_entity_delivery_passes_if_one_matches(self):
        payload = _qb_payload("Customer", "Invoice", operation="Update")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "on_invoice_update"}) is True

    def test_empty_payload_skipped(self):
        assert QuickBooksNode.filter_trigger_payload({}, {"operation": "on_invoice_update"}) is False

    def test_current_docs_payload_shape_passes(self):
        payload = _qb_cloudevents_payload(("Invoice", "310687"), operation="updated")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "on_invoice_update"}) is True

    def test_current_docs_operation_mismatch_skipped(self):
        payload = _qb_cloudevents_payload(("Invoice", "310687"), operation="created")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "on_invoice_update"}) is False

    def test_payroll_entity_payload_shape_passes(self):
        payload = _qb_cloudevents_payload(("Payslips", "310687"), operation="updated")
        assert QuickBooksNode.filter_trigger_payload(payload, {"operation": "on_payslips_update"}) is True

    def test_realm_filter_scopes_current_docs_payload(self):
        payload = _qb_cloudevents_payload(("Invoice", "111"), ("Invoice", "222"), operation="updated")
        assert QuickBooksNode.filter_trigger_payload(
            payload, {"operation": "on_invoice_update", "realm_id": "222"}
        ) is True
        assert QuickBooksNode.filter_trigger_payload(
            payload, {"operation": "on_invoice_update", "realm_id": "333"}
        ) is False

    def test_realm_filter_scopes_legacy_payload(self):
        payload = _qb_payload("Invoice", operation="Update")
        assert QuickBooksNode.filter_trigger_payload(
            payload, {"operation": "on_invoice_update", "realm_id": "123"}
        ) is True
        assert QuickBooksNode.filter_trigger_payload(
            payload, {"operation": "on_invoice_update", "realm_id": "999"}
        ) is False


class TestQuickBooksErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, oauth_credentials):
        config = QuickBooksNodeConfig(
            config=QuickBooksReadInvoiceConfig(invoice_id="missing"),
            credentials=oauth_credentials,
        )
        node = create_quickbooks_node(config)
        error_body = {
            "Fault": {
                "Error": [{"Message": "Object Not Found", "Detail": "Invoice missing not found"}],
                "type": "ValidationFault",
            }
        }
        result = await _run(node, 404, error_body)
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = QuickBooksNodeConfig(config=QuickBooksGetCompanyInfoConfig(), credentials=None)
        node = create_quickbooks_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestQuickBooksDynamicOptionsMock:
    @staticmethod
    def _patches(query_response):
        """Patch the module-level request helper so load_field_options runs without a live API."""
        return patch(
            "nodes.quickbooks_node._quickbooks_request",
            return_value={"status": "success", "data": {"QueryResponse": query_response}},
        )

    @staticmethod
    def _credential():
        return {
            "access_token": "qb_access_token",
            "realm_id": "123",
            "is_sandbox": True,
        }

    @pytest.mark.asyncio
    async def test_load_customer_options(self):
        with self._patches({"Customer": [{"Id": "9", "DisplayName": "Acme Inc"}]}) as mock_req:
            result = await QuickBooksNode.load_field_options(
                "customer_id", self._credential()
            )
        # Verify the query targets the Customer entity.
        assert "FROM Customer" in mock_req.call_args.kwargs["params"]["query"]
        assert result["options"] == [{"label": "Acme Inc", "value": "9"}]

    @pytest.mark.asyncio
    async def test_load_vendor_options(self):
        with self._patches({"Vendor": [{"Id": "20", "DisplayName": "Supplier LLC"}]}) as mock_req:
            result = await QuickBooksNode.load_field_options(
                "vendor_id", self._credential()
            )
        assert "FROM Vendor" in mock_req.call_args.kwargs["params"]["query"]
        assert result["options"] == [{"label": "Supplier LLC", "value": "20"}]

    @pytest.mark.asyncio
    async def test_load_item_options(self):
        with self._patches({"Item": [{"Id": "70", "Name": "Consulting"}]}) as mock_req:
            result = await QuickBooksNode.load_field_options(
                "item_id", self._credential()
            )
        assert "FROM Item" in mock_req.call_args.kwargs["params"]["query"]
        assert result["options"] == [{"label": "Consulting", "value": "70"}]

    @pytest.mark.asyncio
    async def test_load_account_options(self):
        with self._patches({"Account": [{"Id": "80", "Name": "Marketing"}]}) as mock_req:
            result = await QuickBooksNode.load_field_options(
                "account_id", self._credential()
            )
        assert "FROM Account" in mock_req.call_args.kwargs["params"]["query"]
        assert result["options"] == [{"label": "Marketing", "value": "80"}]

    @pytest.mark.asyncio
    async def test_load_income_account_options(self):
        """income_account_id resolves against the same Account entity."""
        with self._patches({"Account": [{"Id": "79", "Name": "Services Income"}]}) as mock_req:
            result = await QuickBooksNode.load_field_options(
                "income_account_id", self._credential()
            )
        assert "FROM Account" in mock_req.call_args.kwargs["params"]["query"]
        assert result["options"] == [{"label": "Services Income", "value": "79"}]

    @pytest.mark.asyncio
    async def test_load_ap_account_options(self):
        """ap_account_id also resolves against the Account entity."""
        with self._patches({"Account": [{"Id": "33", "Name": "Accounts Payable"}]}) as mock_req:
            result = await QuickBooksNode.load_field_options(
                "ap_account_id", self._credential()
            )
        assert "FROM Account" in mock_req.call_args.kwargs["params"]["query"]
        assert result["options"] == [{"label": "Accounts Payable", "value": "33"}]

    @pytest.mark.asyncio
    async def test_unknown_field_returns_empty(self):
        """A field with no dynamic-options mapping yields no options and makes no request."""
        with patch("nodes.quickbooks_node._quickbooks_request") as mock_req:
            result = await QuickBooksNode.load_field_options(
                "invoice_id", self._credential()
            )
        assert result == {"options": []}
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_collects_multiple_pages(self):
        first_page = [
            {"Id": str(i), "DisplayName": f"Customer {i}"}
            for i in range(1, 201)
        ]
        responses = [
            {"status": "success", "data": {"QueryResponse": {"Customer": first_page}}},
            {"status": "success", "data": {"QueryResponse": {"Customer": [{"Id": "201", "DisplayName": "Beta"}]}}},
        ]
        with patch("nodes.quickbooks_node._quickbooks_request", side_effect=responses) as mock_req:
            result = await QuickBooksNode.load_field_options(
                "customer_id",
                self._credential(),
                search="beta",
            )
        assert mock_req.call_count == 2
        assert result["options"] == [{"label": "Beta", "value": "201"}]
