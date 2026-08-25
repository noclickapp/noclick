"""
Mock tests for the Freshsales (Freshworks CRM) REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Contacts: create, get, update, upsert, delete, list (view)
- Accounts: create, get, update, list (view)
- Deals: create, get, update, list (view)
- Tasks: create, list, update/complete
- Appointments: create, list
- Activities: note, sales activity, phone call
- Search / Lookup
- Selectors / Settings: owners, deal stages, contact fields
- Marketing Lists: list, add contacts
- Trigger: receive_webhook passthrough
- Error handling: API errors, missing credentials
- Dynamic options: owner & deal-stage dropdowns
- Base URL builder
"""

import pytest
from unittest.mock import Mock, patch

from nodes.freshsales_node import (
    FreshsalesNode,
    FreshsalesNodeConfig,
    FreshsalesApiKeyCredential,
    FreshsalesCreateContactConfig,
    FreshsalesGetContactConfig,
    FreshsalesUpdateContactConfig,
    FreshsalesUpsertContactConfig,
    FreshsalesDeleteContactConfig,
    FreshsalesListContactsConfig,
    FreshsalesCreateAccountConfig,
    FreshsalesGetAccountConfig,
    FreshsalesUpdateAccountConfig,
    FreshsalesListAccountsConfig,
    FreshsalesCreateDealConfig,
    FreshsalesGetDealConfig,
    FreshsalesUpdateDealConfig,
    FreshsalesListDealsConfig,
    FreshsalesCreateTaskConfig,
    FreshsalesListTasksConfig,
    FreshsalesUpdateTaskConfig,
    FreshsalesCreateAppointmentConfig,
    FreshsalesListAppointmentsConfig,
    FreshsalesCreateNoteConfig,
    FreshsalesCreateSalesActivityConfig,
    FreshsalesLogPhoneCallConfig,
    FreshsalesSearchConfig,
    FreshsalesLookupConfig,
    FreshsalesListOwnersConfig,
    FreshsalesListDealStagesConfig,
    FreshsalesGetContactFieldsConfig,
    FreshsalesListMarketingListsConfig,
    FreshsalesAddContactsToListConfig,
    FreshsalesReceiveWebhookConfig,
    FreshsalesCloneContactConfig,
    FreshsalesForgetContactConfig,
    FreshsalesGetContactActivitiesConfig,
    FreshsalesListContactViewsConfig,
    FreshsalesUpsertAccountConfig,
    FreshsalesDeleteAccountConfig,
    FreshsalesCloneAccountConfig,
    FreshsalesForgetAccountConfig,
    FreshsalesListAccountViewsConfig,
    FreshsalesDeleteDealConfig,
    FreshsalesCloneDealConfig,
    FreshsalesForgetDealConfig,
    FreshsalesListDealViewsConfig,
    FreshsalesGetTaskConfig,
    FreshsalesDeleteTaskConfig,
    FreshsalesGetAppointmentConfig,
    FreshsalesUpdateAppointmentConfig,
    FreshsalesDeleteAppointmentConfig,
    FreshsalesUpdateNoteConfig,
    FreshsalesDeleteNoteConfig,
    FreshsalesListSalesActivitiesConfig,
    FreshsalesGetSalesActivityConfig,
    FreshsalesUpdateSalesActivityConfig,
    FreshsalesDeleteSalesActivityConfig,
    FreshsalesFilteredSearchConfig,
    FreshsalesListSelectorConfig,
    FreshsalesGetModuleFieldsConfig,
    FreshsalesGetListContactsConfig,
    FreshsalesRemoveContactsFromListConfig,
    FreshsalesCreateCustomRecordConfig,
    FreshsalesGetCustomRecordConfig,
    FreshsalesUpdateCustomRecordConfig,
    FreshsalesDeleteCustomRecordConfig,
    FreshsalesCreateDocumentLinkConfig,
    FreshsalesListDocumentAssociationsConfig,
    _build_base_url,
)


@pytest.fixture
def credentials():
    return FreshsalesApiKeyCredential(
        account_domain="acme.myfreshworks.com", api_key="fs_test_key_12345"
    )


def create_freshsales_node(config):
    return FreshsalesNode(
        node_id="test-freshsales-node",
        node_type="automation-freshsales",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
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


def _run(config, status_code, json_data):
    """Execute a node config against a mocked client and return the result."""
    node = create_freshsales_node(config)
    mock_client = create_mock_client(status_code, json_data)
    return node, mock_client


# ============================================================================
# Contacts
# ============================================================================


class TestFreshsalesContactsMock:
    @pytest.mark.asyncio
    async def test_create_contact(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesCreateContactConfig(
                email="ada@example.com", first_name="Ada", last_name="Lovelace"
            ),
            credentials=credentials,
        )
        node, client = _run(config, 201, {"contact": {"id": 1, "email": "ada@example.com"}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_contact"
        assert result["data"]["contact"]["id"] == 1

    @pytest.mark.asyncio
    async def test_get_contact(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesGetContactConfig(contact_id="1", include="owner"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"contact": {"id": 1}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_contact"
        assert result["data"]["contact"]["id"] == 1

    @pytest.mark.asyncio
    async def test_update_contact(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesUpdateContactConfig(contact_id="1", job_title="CTO"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"contact": {"id": 1, "job_title": "CTO"}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_contact"

    @pytest.mark.asyncio
    async def test_upsert_contact(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesUpsertContactConfig(email="ada@example.com", first_name="Ada"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"contact": {"id": 1}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upsert_contact"

    @pytest.mark.asyncio
    async def test_delete_contact(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesDeleteContactConfig(contact_id="1"), credentials=credentials
        )
        node, client = _run(config, 204, None)
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_contact"
        assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_list_contacts(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesListContactsConfig(view_id="123", page="2", sort_type="asc"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"contacts": [{"id": 1}, {"id": 2}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_contacts"
        assert len(result["data"]["contacts"]) == 2


# ============================================================================
# Accounts
# ============================================================================


class TestFreshsalesAccountsMock:
    @pytest.mark.asyncio
    async def test_create_account(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesCreateAccountConfig(name="Acme Inc", website="https://acme.com"),
            credentials=credentials,
        )
        node, client = _run(config, 201, {"sales_account": {"id": 5, "name": "Acme Inc"}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_account"
        assert result["data"]["sales_account"]["id"] == 5

    @pytest.mark.asyncio
    async def test_get_account(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesGetAccountConfig(account_id="5"), credentials=credentials
        )
        node, client = _run(config, 200, {"sales_account": {"id": 5}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_account"

    @pytest.mark.asyncio
    async def test_update_account(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesUpdateAccountConfig(account_id="5", phone="+12025550100"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"sales_account": {"id": 5}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_account"

    @pytest.mark.asyncio
    async def test_list_accounts(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesListAccountsConfig(view_id="321"), credentials=credentials
        )
        node, client = _run(config, 200, {"sales_accounts": [{"id": 5}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_accounts"


# ============================================================================
# Deals
# ============================================================================


class TestFreshsalesDealsMock:
    @pytest.mark.asyncio
    async def test_create_deal(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesCreateDealConfig(name="Big Deal", amount="50000"),
            credentials=credentials,
        )
        node, client = _run(config, 201, {"deal": {"id": 9, "name": "Big Deal"}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_deal"
        assert result["data"]["deal"]["id"] == 9

    @pytest.mark.asyncio
    async def test_get_deal(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesGetDealConfig(deal_id="9"), credentials=credentials
        )
        node, client = _run(config, 200, {"deal": {"id": 9}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_deal"

    @pytest.mark.asyncio
    async def test_update_deal(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesUpdateDealConfig(deal_id="9", deal_stage_id="3"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"deal": {"id": 9}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_deal"

    @pytest.mark.asyncio
    async def test_list_deals(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesListDealsConfig(view_id="654"), credentials=credentials
        )
        node, client = _run(config, 200, {"deals": [{"id": 9}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_deals"


# ============================================================================
# Tasks / Appointments
# ============================================================================


class TestFreshsalesTasksMock:
    @pytest.mark.asyncio
    async def test_create_task(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesCreateTaskConfig(title="Follow up", due_date="2026-07-01T10:00:00Z"),
            credentials=credentials,
        )
        node, client = _run(config, 201, {"task": {"id": 11}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_task"

    @pytest.mark.asyncio
    async def test_list_tasks(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesListTasksConfig(task_filter="open"), credentials=credentials
        )
        node, client = _run(config, 200, {"tasks": [{"id": 11}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_tasks"

    @pytest.mark.asyncio
    async def test_update_task_complete(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesUpdateTaskConfig(task_id="11", mark_complete="true"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"task": {"id": 11, "status": 1}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_task"
        assert result["data"]["task"]["status"] == 1

    @pytest.mark.asyncio
    async def test_create_appointment(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesCreateAppointmentConfig(
                title="Demo", from_date="2026-07-01T10:00:00Z", end_date="2026-07-01T11:00:00Z"
            ),
            credentials=credentials,
        )
        node, client = _run(config, 201, {"appointment": {"id": 21}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_appointment"

    @pytest.mark.asyncio
    async def test_list_appointments(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesListAppointmentsConfig(appointment_filter="upcoming"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"appointments": [{"id": 21}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_appointments"


# ============================================================================
# Activities
# ============================================================================


class TestFreshsalesActivitiesMock:
    @pytest.mark.asyncio
    async def test_create_note(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesCreateNoteConfig(
                description="Called the lead", targetable_type="Contact", targetable_id="1"
            ),
            credentials=credentials,
        )
        node, client = _run(config, 201, {"note": {"id": 31}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_note"

    @pytest.mark.asyncio
    async def test_create_sales_activity(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesCreateSalesActivityConfig(
                title="Intro call",
                sales_activity_type_id="2",
                targetable_type="Contact",
                targetable_id="1",
                start_date="2026-12-31T10:00:00Z",
                end_date="2026-12-31T11:00:00Z",
            ),
            credentials=credentials,
        )
        node, client = _run(config, 201, {"sales_activity": {"id": 41}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_sales_activity"

    @pytest.mark.asyncio
    async def test_log_phone_call(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesLogPhoneCallConfig(
                call_direction="outgoing", targetable_type="Contact", targetable_id="1"
            ),
            credentials=credentials,
        )
        node, client = _run(config, 201, {"phone_call": {"id": 51}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "log_phone_call"


# ============================================================================
# Search / Lookup / Selectors / Settings
# ============================================================================


class TestFreshsalesSearchMock:
    @pytest.mark.asyncio
    async def test_search(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesSearchConfig(query="ada", include="contact"), credentials=credentials
        )
        node, client = _run(config, 200, [{"id": 1, "type": "contact"}])
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search"
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_lookup(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesLookupConfig(value="ada@example.com", field="email"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"contacts": {"contacts": [{"id": 1}]}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "lookup"

    @pytest.mark.asyncio
    async def test_list_owners(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesListOwnersConfig(), credentials=credentials
        )
        node, client = _run(config, 200, {"users": [{"id": 7, "display_name": "Sam"}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_owners"

    @pytest.mark.asyncio
    async def test_list_deal_stages(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesListDealStagesConfig(), credentials=credentials
        )
        node, client = _run(config, 200, {"deal_stages": [{"id": 3, "name": "Negotiation"}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_deal_stages"

    @pytest.mark.asyncio
    async def test_get_contact_fields(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesGetContactFieldsConfig(), credentials=credentials
        )
        node, client = _run(config, 200, {"fields": [{"name": "email"}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_contact_fields"


# ============================================================================
# Marketing Lists
# ============================================================================


class TestFreshsalesListsMock:
    @pytest.mark.asyncio
    async def test_list_marketing_lists(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesListMarketingListsConfig(), credentials=credentials
        )
        node, client = _run(config, 200, {"lists": [{"id": 101, "name": "Newsletter"}]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_marketing_lists"

    @pytest.mark.asyncio
    async def test_add_contacts_to_list(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesAddContactsToListConfig(list_id="101", contact_ids="1, 2, 3"),
            credentials=credentials,
        )
        node, client = _run(config, 200, {"succeed": [1, 2, 3]})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "add_contacts_to_list"


# ============================================================================
# Trigger
# ============================================================================


class TestFreshsalesTriggerMock:
    @pytest.mark.asyncio
    async def test_receive_webhook_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = FreshsalesNodeConfig(
            config=FreshsalesReceiveWebhookConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_freshsales_node(config)
        payload = {"event": "ContactCreated", "data": {"id": 1}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "receive_webhook"
        assert result["data"]["event"] == "ContactCreated"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"


# ============================================================================
# Error handling
# ============================================================================


class TestFreshsalesErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        config = FreshsalesNodeConfig(
            config=FreshsalesGetContactConfig(contact_id="missing"), credentials=credentials
        )
        node, client = _run(config, 404, {"errors": {"message": "Contact not found"}})
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = FreshsalesNodeConfig(config=FreshsalesListOwnersConfig(), credentials=None)
        node = create_freshsales_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestFreshsalesDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_owner_options(self):
        cred = {"api_key": "fs_test", "account_domain": "acme.myfreshworks.com"}
        with patch(
            "nodes.freshsales_node._freshsales_request",
            return_value={
                "status": "success",
                "data": {"users": [{"id": 7, "display_name": "Sam Sales"}]},
            },
        ):
            result = await FreshsalesNode.load_field_options("owner_id", cred)
        assert "options" in result
        assert result["options"][0]["value"] == "7"
        assert result["options"][0]["label"] == "Sam Sales"

    @pytest.mark.asyncio
    async def test_load_deal_stage_options(self):
        cred = {"api_key": "fs_test", "account_domain": "acme.myfreshworks.com"}
        with patch(
            "nodes.freshsales_node._freshsales_request",
            return_value={
                "status": "success",
                "data": {"deal_stages": [{"id": 3, "name": "Negotiation"}]},
            },
        ):
            result = await FreshsalesNode.load_field_options("deal_stage_id", cred)
        assert result["options"][0]["value"] == "3"
        assert result["options"][0]["label"] == "Negotiation"

    @pytest.mark.asyncio
    async def test_load_options_missing_credential_returns_empty(self):
        result = await FreshsalesNode.load_field_options("owner_id", {})
        assert result == {"options": []}


def create_capturing_client(captured, status_code=200, json_data=None):
    """Mock client recording the (method, url, params, json) of each request."""
    mock_response = create_mock_response(status_code, json_data if json_data is not None else {})
    mock_client = Mock()

    async def async_request(method=None, url=None, headers=None, params=None, json=None):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        return mock_response

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.request = async_request
    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


class TestFreshsalesNewOperationsRouting:
    """Verify every added operation dispatches to the correct method + endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cfg,method,frag", [
        (FreshsalesCloneContactConfig(contact_id="1"), "POST", "/api/contacts/1/clone"),
        (FreshsalesForgetContactConfig(contact_id="1"), "DELETE", "/api/contacts/1/forget"),
        (FreshsalesGetContactActivitiesConfig(contact_id="1"), "GET", "/api/contacts/1/activities"),
        (FreshsalesListContactViewsConfig(), "GET", "/api/contacts/filters"),
        (FreshsalesUpsertAccountConfig(name="Acme"), "POST", "/api/sales_accounts/upsert"),
        (FreshsalesDeleteAccountConfig(account_id="2"), "DELETE", "/api/sales_accounts/2"),
        (FreshsalesCloneAccountConfig(account_id="2"), "POST", "/api/sales_accounts/2/clone"),
        (FreshsalesForgetAccountConfig(account_id="2"), "DELETE", "/api/sales_accounts/2/forget"),
        (FreshsalesListAccountViewsConfig(), "GET", "/api/sales_accounts/filters"),
        (FreshsalesDeleteDealConfig(deal_id="3"), "DELETE", "/api/deals/3"),
        (FreshsalesCloneDealConfig(deal_id="3"), "POST", "/api/deals/3/clone"),
        (FreshsalesForgetDealConfig(deal_id="3"), "DELETE", "/api/deals/3/forget"),
        (FreshsalesListDealViewsConfig(), "GET", "/api/deals/filters"),
        (FreshsalesGetTaskConfig(task_id="4"), "GET", "/api/tasks/4"),
        (FreshsalesDeleteTaskConfig(task_id="4"), "DELETE", "/api/tasks/4"),
        (FreshsalesGetAppointmentConfig(appointment_id="5"), "GET", "/api/appointments/5"),
        (FreshsalesUpdateAppointmentConfig(appointment_id="5", title="x"), "PUT", "/api/appointments/5"),
        (FreshsalesDeleteAppointmentConfig(appointment_id="5"), "DELETE", "/api/appointments/5"),
        (FreshsalesUpdateNoteConfig(note_id="6", description="x"), "PUT", "/api/notes/6"),
        (FreshsalesDeleteNoteConfig(note_id="6"), "DELETE", "/api/notes/6"),
        (FreshsalesListSalesActivitiesConfig(), "GET", "/api/sales_activities"),
        (FreshsalesGetSalesActivityConfig(sales_activity_id="7"), "GET", "/api/sales_activities/7"),
        (FreshsalesUpdateSalesActivityConfig(sales_activity_id="7", title="x"), "PUT", "/api/sales_activities/7"),
        (FreshsalesDeleteSalesActivityConfig(sales_activity_id="7"), "DELETE", "/api/sales_activities/7"),
        (FreshsalesFilteredSearchConfig(entity="contact", filter_rule_json="[]"), "POST", "/api/filtered_search/contact"),
        (FreshsalesListSelectorConfig(selector="deal_pipelines"), "GET", "/api/selector/deal_pipelines"),
        (FreshsalesGetModuleFieldsConfig(entity="deals"), "GET", "/api/settings/deals/fields"),
        (FreshsalesGetListContactsConfig(list_id="8"), "GET", "/api/contacts/lists/8"),
        (FreshsalesRemoveContactsFromListConfig(list_id="8", contact_ids="1,2"), "PUT", "/api/lists/8/remove_contacts"),
        (FreshsalesCreateCustomRecordConfig(module_name="cm_projects", data_json="{}"), "POST", "/api/custom_module/cm_projects"),
        (FreshsalesGetCustomRecordConfig(module_name="cm_projects", record_id="9"), "GET", "/api/custom_module/cm_projects/9"),
        (FreshsalesUpdateCustomRecordConfig(module_name="cm_projects", record_id="9", data_json="{}"), "PUT", "/api/custom_module/cm_projects/9"),
        (FreshsalesDeleteCustomRecordConfig(module_name="cm_projects", record_id="9"), "DELETE", "/api/custom_module/cm_projects/9"),
        (FreshsalesCreateDocumentLinkConfig(url="https://x", targetable_id="1"), "POST", "/api/document_links"),
        (FreshsalesListDocumentAssociationsConfig(targetable_type="contacts", record_id="1"), "GET", "/api/contacts/1/document_associations"),
    ])
    async def test_routing(self, credentials, cfg, method, frag):
        config = FreshsalesNodeConfig(config=cfg, credentials=credentials)
        node = create_freshsales_node(config)
        captured = {}
        client = create_capturing_client(captured)
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=client):
            result = await node.execute({})
        assert result["status"] == "success", result
        assert captured["method"] == method, f"{cfg.operation}: {captured['method']} != {method}"
        assert frag in captured["url"], f"{cfg.operation}: {frag} not in {captured['url']}"

    @pytest.mark.asyncio
    async def test_filtered_search_body(self, credentials):
        cfg = FreshsalesFilteredSearchConfig(entity="deal", filter_rule_json='[{"attribute":"amount","operator":"is_gt","value":"1000"}]')
        node = create_freshsales_node(FreshsalesNodeConfig(config=cfg, credentials=credentials))
        captured = {}
        with patch("nodes.freshsales_node.httpx.AsyncClient", return_value=create_capturing_client(captured)):
            await node.execute({})
        assert captured["json"]["filter_rule"][0]["attribute"] == "amount"

# ============================================================================
# Base URL builder
# ============================================================================


class TestFreshsalesBaseUrl:
    def test_build_base_url_full_domain(self):
        assert _build_base_url("acme.myfreshworks.com") == "https://acme.myfreshworks.com/crm/sales"

    def test_build_base_url_alias_only(self):
        assert _build_base_url("acme") == "https://acme.myfreshworks.com/crm/sales"

    def test_build_base_url_strips_scheme_and_path(self):
        assert (
            _build_base_url("https://acme.myfreshworks.com/crm/sales/")
            == "https://acme.myfreshworks.com/crm/sales"
        )
