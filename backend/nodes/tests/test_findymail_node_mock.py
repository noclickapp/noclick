"""
Mock tests for the Findymail REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Finder: find email from name/domain/business-profile, reverse email, find phone,
  get company, find employees
- Verifier: verify email
- Intellimatch: search, status, data
- Discovery: lookalike search, technologies lookup/search
- Signals: list signals, get signal, list/create/update/delete monitors
- Lists: list/create/update/delete contact lists, get contacts
- Credits: get credits, usage summary
- Trigger: on_signal_match passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: contact-list dropdown
"""

import hashlib
import hmac

import httpx
import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nodes.findymail_node import (
    FindymailNode,
    FindymailNodeConfig,
    FindymailApiKeyCredential,
    FindymailFindEmailFromNameConfig,
    FindymailFindEmailsFromDomainConfig,
    FindymailFindFromBusinessProfileConfig,
    FindymailReverseEmailConfig,
    FindymailFindPhoneConfig,
    FindymailGetCompanyConfig,
    FindymailFindEmployeesConfig,
    FindymailVerifyEmailConfig,
    FindymailIntellimatchSearchConfig,
    FindymailIntellimatchStatusConfig,
    FindymailIntellimatchDataConfig,
    FindymailListExclusionListsConfig,
    FindymailCreateExclusionListConfig,
    FindymailGetExclusionListConfig,
    FindymailUpdateExclusionListConfig,
    FindymailDeleteExclusionListConfig,
    FindymailListExcludedDomainsConfig,
    FindymailAddExcludedDomainsConfig,
    FindymailRemoveExcludedDomainsConfig,
    FindymailLookalikeSearchConfig,
    FindymailTechnologiesLookupConfig,
    FindymailTechnologiesSearchConfig,
    FindymailListSignalsConfig,
    FindymailGetSignalConfig,
    FindymailListSignalMonitorsConfig,
    FindymailCreateSignalMonitorConfig,
    FindymailUpdateSignalMonitorConfig,
    FindymailDeleteSignalMonitorConfig,
    FindymailListContactListsConfig,
    FindymailCreateContactListConfig,
    FindymailUpdateContactListConfig,
    FindymailDeleteContactListConfig,
    FindymailGetContactsConfig,
    FindymailGetCreditsConfig,
    FindymailGetUsageSummaryConfig,
    FindymailGetTeamUsageSummaryConfig,
    FindymailSignalTriggerConfig,
    _comma_list,
    _optional_int,
    _optional_bool,
    _optional_int_list,
    _build_icp_filters,
    _build_signal_monitor_payload,
)


@pytest.fixture
def api_key_credentials():
    return FindymailApiKeyCredential(api_key="fm_test_key_12345")


def create_findymail_node(config):
    return FindymailNode(
        node_id="test-findymail-node",
        node_type="automation-findymail",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, text="", json_exc=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text

    def json_fn():
        if json_exc is not None:
            raise json_exc
        return json_data if json_data is not None else {}

    mock_response.json = json_fn
    return mock_response


def create_mock_client(status_code=200, json_data=None, text="", json_exc=None, request_exc=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, text=text, json_exc=json_exc)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        if request_exc is not None:
            raise request_exc
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


async def _run(config_obj, api_key_credentials, status_code, json_data):
    config = FindymailNodeConfig(config=config_obj, credentials=api_key_credentials)
    node = create_findymail_node(config)
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.findymail_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


class TestFindymailFinderMock:
    @pytest.mark.asyncio
    async def test_find_email_from_name(self, api_key_credentials):
        result = await _run(
            FindymailFindEmailFromNameConfig(name="Ada Lovelace", domain="acme.com"),
            api_key_credentials, 200, {"contact": {"email": "ada@acme.com"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "find_email_from_name"
        assert result["data"]["contact"]["email"] == "ada@acme.com"

    @pytest.mark.asyncio
    async def test_find_emails_from_domain(self, api_key_credentials):
        result = await _run(
            FindymailFindEmailsFromDomainConfig(domain="acme.com"),
            api_key_credentials, 200, {"contacts": [{"email": "a@acme.com"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "find_emails_from_domain"

    @pytest.mark.asyncio
    async def test_find_emails_from_domain_sends_roles(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailFindEmailsFromDomainConfig(
                domain="acme.com",
                roles="Founder, CEO",
                webhook_url="https://example.com/webhook",
            ),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        with patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "success", "action": "find_emails_from_domain", "data": {}},
        ) as mock_req:
            await node.execute({})
        assert mock_req.call_args.kwargs["json_body"] == {
            "domain": "acme.com",
            "roles": ["Founder", "CEO"],
            "webhook_url": "https://example.com/webhook",
        }

    @pytest.mark.asyncio
    async def test_find_from_business_profile(self, api_key_credentials):
        result = await _run(
            FindymailFindFromBusinessProfileConfig(linkedin_url="https://linkedin.com/in/ada"),
            api_key_credentials, 200, {"contact": {"email": "ada@acme.com"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "find_from_business_profile"

    @pytest.mark.asyncio
    async def test_reverse_email(self, api_key_credentials):
        result = await _run(
            FindymailReverseEmailConfig(email="ada@acme.com", with_profile="true"),
            api_key_credentials, 200, {"contact": {"linkedin_url": "https://linkedin.com/in/ada"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "reverse_email"

    @pytest.mark.asyncio
    async def test_find_phone(self, api_key_credentials):
        result = await _run(
            FindymailFindPhoneConfig(linkedin_url="https://linkedin.com/in/ada"),
            api_key_credentials, 200, {"contact": {"phone": "+12025550106"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "find_phone"
        assert result["data"]["contact"]["phone"] == "+12025550106"

    @pytest.mark.asyncio
    async def test_get_company(self, api_key_credentials):
        result = await _run(
            FindymailGetCompanyConfig(domain="acme.com"),
            api_key_credentials, 200, {"company": {"name": "Acme"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_company"

    @pytest.mark.asyncio
    async def test_find_employees(self, api_key_credentials):
        result = await _run(
            FindymailFindEmployeesConfig(website="acme.com", job_titles="CEO, VP Sales", count="5"),
            api_key_credentials, 200, {"contacts": [{"name": "Ada"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "find_employees"


class TestFindymailVerifierMock:
    @pytest.mark.asyncio
    async def test_verify_email(self, api_key_credentials):
        result = await _run(
            FindymailVerifyEmailConfig(email="ada@acme.com"),
            api_key_credentials, 200, {"email": "ada@acme.com", "verified": True, "provider": "google"},
        )
        assert result["status"] == "success"
        assert result["action"] == "verify_email"
        assert result["data"]["verified"] is True


class TestFindymailIntellimatchMock:
    @pytest.mark.asyncio
    async def test_intellimatch_search(self, api_key_credentials):
        result = await _run(
            FindymailIntellimatchSearchConfig(query="VPs of Sales at SaaS companies", limit="100"),
            api_key_credentials, 200, {"hash": "exp_1"},
        )
        assert result["status"] == "success"
        assert result["action"] == "intellimatch_search"
        assert result["data"]["hash"] == "exp_1"

    @pytest.mark.asyncio
    async def test_intellimatch_search_builds_extended_config(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailIntellimatchSearchConfig(
                query="SaaS companies",
                limit="10",
                find_contact="true",
                find_email="true",
                find_phone="false",
                target_job_titles="CEO, CTO",
                lead_list_id="12",
                mode="targeted",
                require_email="true",
                add_to_exclusion_list="true",
                exclusion_list_id="18",
                exclusion_filter_list_ids="1, 2, 3",
            ),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        with patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "success", "action": "intellimatch_search", "data": {}},
        ) as mock_req:
            await node.execute({})
        assert mock_req.call_args.kwargs["json_body"] == {
            "query": "SaaS companies",
            "limit": 10,
            "config": {
                "find_contact": True,
                "find_email": True,
                "find_phone": False,
                "target_job_titles": ["CEO", "CTO"],
                "lead_list_id": 12,
                "mode": "targeted",
                "require_email": True,
                "add_to_exclusion_list": True,
                "exclusion_list_id": 18,
                "exclusion_filter_list_ids": [1, 2, 3],
            },
        }

    @pytest.mark.asyncio
    async def test_intellimatch_status_uses_hash_param(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailIntellimatchStatusConfig(hash="abc123"),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        with patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "success", "action": "intellimatch_status", "data": {}},
        ) as mock_req:
            await node.execute({})
        assert mock_req.call_args.kwargs["params"] == {"hash": "abc123"}

    @pytest.mark.asyncio
    async def test_intellimatch_status(self, api_key_credentials):
        result = await _run(
            FindymailIntellimatchStatusConfig(hash="exp_1"),
            api_key_credentials, 200, {"status": "completed"},
        )
        assert result["status"] == "success"
        assert result["action"] == "intellimatch_status"

    @pytest.mark.asyncio
    async def test_intellimatch_data(self, api_key_credentials):
        result = await _run(
            FindymailIntellimatchDataConfig(hash="exp_1", page="1", per_page="100"),
            api_key_credentials, 200, {"data": [{"email": "a@acme.com"}], "current_page": 1},
        )
        assert result["status"] == "success"
        assert result["action"] == "intellimatch_data"

    @pytest.mark.asyncio
    async def test_list_exclusion_lists(self, api_key_credentials):
        result = await _run(
            FindymailListExclusionListsConfig(),
            api_key_credentials,
            200,
            {"lists": [{"id": 1, "name": "Competitors"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_exclusion_lists"

    @pytest.mark.asyncio
    async def test_create_exclusion_list(self, api_key_credentials):
        result = await _run(
            FindymailCreateExclusionListConfig(name="Competitors", is_shared="true"),
            api_key_credentials,
            200,
            {"id": 1, "name": "Competitors", "is_shared": True},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_exclusion_list"

    @pytest.mark.asyncio
    async def test_get_exclusion_list(self, api_key_credentials):
        result = await _run(
            FindymailGetExclusionListConfig(excluded_domain_list_id="1"),
            api_key_credentials,
            200,
            {"id": 1, "name": "Competitors"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_exclusion_list"

    @pytest.mark.asyncio
    async def test_update_exclusion_list(self, api_key_credentials):
        result = await _run(
            FindymailUpdateExclusionListConfig(
                excluded_domain_list_id="1", name="Updated", is_shared="false"
            ),
            api_key_credentials,
            200,
            {"id": 1, "name": "Updated", "is_shared": False},
        )
        assert result["status"] == "success"
        assert result["action"] == "update_exclusion_list"

    @pytest.mark.asyncio
    async def test_delete_exclusion_list(self, api_key_credentials):
        result = await _run(
            FindymailDeleteExclusionListConfig(excluded_domain_list_id="1"),
            api_key_credentials,
            200,
            {"success": True},
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_exclusion_list"

    @pytest.mark.asyncio
    async def test_list_excluded_domains(self, api_key_credentials):
        result = await _run(
            FindymailListExcludedDomainsConfig(
                query="example.com",
                excluded_domain_list_id="1",
                per_page="25",
                page="2",
            ),
            api_key_credentials,
            200,
            {"data": [{"id": 7, "domain": "example.com"}], "current_page": 2},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_excluded_domains"

    @pytest.mark.asyncio
    async def test_add_excluded_domains(self, api_key_credentials):
        result = await _run(
            FindymailAddExcludedDomainsConfig(
                domains="example.com, blocked.io",
                excluded_domain_list_id="1",
            ),
            api_key_credentials,
            200,
            {"success": True, "processed_immediately": 2},
        )
        assert result["status"] == "success"
        assert result["action"] == "add_excluded_domains"

    @pytest.mark.asyncio
    async def test_remove_excluded_domains(self, api_key_credentials):
        result = await _run(
            FindymailRemoveExcludedDomainsConfig(ids="7, 8"),
            api_key_credentials,
            200,
            {"success": True, "deleted_count": 2},
        )
        assert result["status"] == "success"
        assert result["action"] == "remove_excluded_domains"


class TestFindymailDiscoveryMock:
    @pytest.mark.asyncio
    async def test_lookalike_search(self, api_key_credentials):
        result = await _run(
            FindymailLookalikeSearchConfig(domains="acme.com, globex.com", limit="10"),
            api_key_credentials, 200, {"companies": [{"domain": "initech.com"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "lookalike_search"

    @pytest.mark.asyncio
    async def test_technologies_lookup(self, api_key_credentials):
        result = await _run(
            FindymailTechnologiesLookupConfig(domain="acme.com"),
            api_key_credentials, 200, {"technologies": ["Shopify", "Stripe"]},
        )
        assert result["status"] == "success"
        assert result["action"] == "technologies_lookup"

    @pytest.mark.asyncio
    async def test_technologies_search(self, api_key_credentials):
        result = await _run(
            FindymailTechnologiesSearchConfig(query="Shopify"),
            api_key_credentials, 200, {"results": [{"name": "Shopify"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "technologies_search"

    @pytest.mark.asyncio
    async def test_technologies_search_uses_q_param(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailTechnologiesSearchConfig(query="Shopify"),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        with patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "success", "action": "technologies_search", "data": {}},
        ) as mock_req:
            await node.execute({})
        assert mock_req.call_args.kwargs["params"] == {"q": "Shopify"}


class TestFindymailSignalsMock:
    @pytest.mark.asyncio
    async def test_list_signals(self, api_key_credentials):
        result = await _run(
            FindymailListSignalsConfig(page="1", per_page="50"),
            api_key_credentials, 200, {"data": [{"id": 1}], "current_page": 1},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_signals"

    @pytest.mark.asyncio
    async def test_get_signal(self, api_key_credentials):
        result = await _run(
            FindymailGetSignalConfig(signal_id="42"),
            api_key_credentials, 200, {"id": 42, "type": "funding"},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_signal"
        assert result["data"]["id"] == 42

    @pytest.mark.asyncio
    async def test_list_signal_monitors(self, api_key_credentials):
        result = await _run(
            FindymailListSignalMonitorsConfig(ownership="team"),
            api_key_credentials, 200, {"monitors": [{"id": 1}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_signal_monitors"

    @pytest.mark.asyncio
    async def test_create_signal_monitor(self, api_key_credentials):
        result = await _run(
            FindymailCreateSignalMonitorConfig(
                name="Hiring SDRs",
                signal_type="company_hiring",
                webhook_url="https://x.hooks.example.test",
                enrichment_level="email_phone",
                lead_list_id="42",
                target_companies="acme.com, globex.com",
                is_shared="true",
                icp_industries="Biotechnology, Software",
                icp_employee_count_ranges="51-200, 201-500",
                icp_countries="US, FR",
                icp_job_title_keywords="VP Sales, CTO",
                icp_seniority_levels="11, 13",
                job_offer_title_keywords="account executive, sdr",
            ),
            api_key_credentials, 200, {"monitor": {"id": 7}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_signal_monitor"

    @pytest.mark.asyncio
    async def test_update_signal_monitor(self, api_key_credentials):
        result = await _run(
            FindymailUpdateSignalMonitorConfig(
                monitor_id="7",
                name="Renamed",
                keywords="hiring, fundraise",
                webhook_url="https://x.hooks.example.test",
                engagement_types="like, comment",
                enrichment_level="email",
                lead_list_id="9",
                ai_relevance_prompt="Focus on revenue hires",
                target_companies="acme.com",
                is_shared="false",
                icp_industries="Software",
                icp_employee_count_ranges="51-200",
                icp_countries="US",
                icp_job_title_keywords="VP Sales",
                icp_seniority_levels="11",
                job_offer_title_keywords="ae",
            ),
            api_key_credentials, 200, {"monitor": {"id": 7, "name": "Renamed"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "update_signal_monitor"

    @pytest.mark.asyncio
    async def test_delete_signal_monitor(self, api_key_credentials):
        result = await _run(
            FindymailDeleteSignalMonitorConfig(monitor_id="7"),
            api_key_credentials, 204, None,
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_signal_monitor"


class TestFindymailListsMock:
    @pytest.mark.asyncio
    async def test_list_contact_lists(self, api_key_credentials):
        result = await _run(
            FindymailListContactListsConfig(),
            api_key_credentials, 200, {"lists": [{"id": 1, "name": "Prospects"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "list_contact_lists"

    @pytest.mark.asyncio
    async def test_create_contact_list(self, api_key_credentials):
        result = await _run(
            FindymailCreateContactListConfig(name="Prospects"),
            api_key_credentials, 200, {"list": {"id": 9, "name": "Prospects"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "create_contact_list"

    @pytest.mark.asyncio
    async def test_update_contact_list(self, api_key_credentials):
        result = await _run(
            FindymailUpdateContactListConfig(list_id="9", name="Renamed", is_shared="true"),
            api_key_credentials, 200, {"list": {"id": 9, "name": "Renamed"}},
        )
        assert result["status"] == "success"
        assert result["action"] == "update_contact_list"

    @pytest.mark.asyncio
    async def test_update_contact_list_uses_is_shared(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailUpdateContactListConfig(
                list_id="9",
                name="Renamed",
                is_shared="false",
            ),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        with patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "success", "action": "update_contact_list", "data": {}},
        ) as mock_req:
            await node.execute({})
        assert mock_req.call_args.kwargs["json_body"] == {
            "name": "Renamed",
            "isShared": False,
        }

    @pytest.mark.asyncio
    async def test_delete_contact_list(self, api_key_credentials):
        result = await _run(
            FindymailDeleteContactListConfig(list_id="9"),
            api_key_credentials, 204, None,
        )
        assert result["status"] == "success"
        assert result["action"] == "delete_contact_list"

    @pytest.mark.asyncio
    async def test_get_contacts(self, api_key_credentials):
        result = await _run(
            FindymailGetContactsConfig(list_id="9"),
            api_key_credentials, 200, {"contacts": [{"email": "a@acme.com"}]},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_contacts"


class TestFindymailCreditsMock:
    @pytest.mark.asyncio
    async def test_get_credits(self, api_key_credentials):
        result = await _run(
            FindymailGetCreditsConfig(),
            api_key_credentials, 200, {"credits": 1000, "verifier_credits": 500},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_credits"
        assert result["data"]["credits"] == 1000

    @pytest.mark.asyncio
    async def test_get_usage_summary(self, api_key_credentials):
        result = await _run(
            FindymailGetUsageSummaryConfig(),
            api_key_credentials, 200, {"finder": 120, "verifier": 30},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_usage_summary"

    @pytest.mark.asyncio
    async def test_get_team_usage_summary(self, api_key_credentials):
        result = await _run(
            FindymailGetTeamUsageSummaryConfig(
                from_date="2025-01-01",
                to_date="2025-01-31",
            ),
            api_key_credentials,
            200,
            {"from": "2025-01-01", "to": "2025-01-31", "members": []},
        )
        assert result["status"] == "success"
        assert result["action"] == "get_team_usage_summary"


class TestFindymailTriggerMock:
    @pytest.mark.asyncio
    async def test_on_signal_match_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = FindymailNodeConfig(
            config=FindymailSignalTriggerConfig(
                signal_type="job_change",
                webhook_url="https://abc.hooks.example.test",
            ),
            credentials=None,
        )
        node = create_findymail_node(config)
        payload = {"event": "signal.matched", "signal": {"id": 7}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_signal_match"
        assert result["data"]["event"] == "signal.matched"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "success", "data": {"id": 99}},
        ) as mock_req:
            extra = await FindymailNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "fm_test"},
                config={
                    "monitor_name": "My Monitor",
                    "signal_type": "company_hiring",
                    "job_offer_title_keywords": "account executive",
                },
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "99"
        assert extra["signing_secret"] is None

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await FindymailNode._unregister_external_webhook(
                credential={"api_key": "fm_test"},
                config={"external_webhook_id": "99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "topsecret"
        body = b'{"event":"signal.matched"}'
        good_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert FindymailNode.verify_webhook_signature(
            body, {"x-findymail-signature": good_sig}, {"signing_secret": secret}
        )
        assert not FindymailNode.verify_webhook_signature(
            body, {"x-findymail-signature": "deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert FindymailNode.verify_webhook_signature(body, {}, {})


class TestFindymailErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        result = await _run(
            FindymailVerifyEmailConfig(email="ada@acme.com"),
            api_key_credentials, 422, {"message": "Invalid email"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 422
        assert "invalid email" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_not_enough_credits_error(self, api_key_credentials):
        result = await _run(
            FindymailFindPhoneConfig(linkedin_url="https://linkedin.com/in/ada"),
            api_key_credentials, 402, {"message": "balance exhausted"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 402
        assert "not enough credits" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_subscription_paused_error(self, api_key_credentials):
        result = await _run(
            FindymailGetCreditsConfig(),
            api_key_credentials,
            423,
            {"message": "account paused"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 423
        assert "subscription paused" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_api_error_falls_back_to_text(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailVerifyEmailConfig(email="ada@acme.com"),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        mock_client = create_mock_client(
            400,
            text="plain failure",
            json_exc=ValueError("invalid json"),
        )
        with patch("nodes.findymail_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["error"] == "plain failure"

    @pytest.mark.asyncio
    async def test_success_response_falls_back_to_raw_text(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailGetCreditsConfig(),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        mock_client = create_mock_client(
            200,
            text='{"credits":100}',
            json_exc=ValueError("invalid json"),
        )
        with patch("nodes.findymail_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["data"] == {"raw": '{"credits":100}'}

    @pytest.mark.asyncio
    async def test_timeout_error(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailGetCreditsConfig(),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        mock_client = create_mock_client(
            request_exc=httpx.TimeoutException("slow"),
        )
        with patch("nodes.findymail_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 408
        assert result["error"] == "Request timed out"

    @pytest.mark.asyncio
    async def test_generic_request_error(self, api_key_credentials):
        config = FindymailNodeConfig(
            config=FindymailGetCreditsConfig(),
            credentials=api_key_credentials,
        )
        node = create_findymail_node(config)
        mock_client = create_mock_client(
            request_exc=RuntimeError("boom ✓"),
        )
        with patch("nodes.findymail_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 500
        assert "boom" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = FindymailNodeConfig(config=FindymailGetCreditsConfig(), credentials=None)
        node = create_findymail_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_missing_valid_config(self):
        node = create_findymail_node(None)
        with pytest.raises(ValueError, match="Valid configuration is required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_unknown_operation(self, api_key_credentials):
        config = FindymailNodeConfig(config=FindymailGetCreditsConfig(), credentials=api_key_credentials)
        node = create_findymail_node(config)
        node.config.config = Mock(operation="unknown_operation")
        with pytest.raises(ValueError, match="Unknown operation"):
            await node.execute({})


class TestFindymailDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_contact_list_options(self):
        with patch(
            "utils.credential_loader.load_credential", return_value={"api_key": "fm_test"}
        ), patch(
            "nodes.findymail_node._findymail_request",
            return_value={
                "status": "success",
                "data": {"lists": [{"id": 9, "name": "Prospects"}]},
            },
        ):
            result = await FindymailNode.load_field_options(
                "list_id", "user-1", {}, credential_ids={"findymail": "cred-1"}, pool=Mock()
            )
        assert "options" in result
        assert result["options"][0]["value"] == "9"
        assert result["options"][0]["label"] == "Prospects"

    @pytest.mark.asyncio
    async def test_load_exclusion_list_options(self):
        with patch(
            "utils.credential_loader.load_credential", return_value={"api_key": "fm_test"}
        ), patch(
            "nodes.findymail_node._findymail_request",
            return_value={
                "status": "success",
                "data": {"lists": [{"id": 5, "name": "Competitors"}, "skip-me"]},
            },
        ):
            result = await FindymailNode.load_field_options(
                "excluded_domain_list_id",
                "user-1",
                {},
                credential_ids={"findymail": "cred-1"},
                pool=Mock(),
            )
        assert result["options"] == [{"label": "Competitors", "value": "5"}]

    @pytest.mark.asyncio
    async def test_load_field_options_unknown_field(self):
        result = await FindymailNode.load_field_options("unknown", "user-1", {})
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_field_options_missing_credential(self):
        with patch("utils.credential_loader.load_credential", return_value=None):
            result = await FindymailNode.load_field_options(
                "list_id",
                "user-1",
                {},
                credential_ids={"findymail": "cred-1"},
                pool=Mock(),
            )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_load_field_options_request_failure(self):
        with patch(
            "utils.credential_loader.load_credential", return_value={"api_key": "fm_test"}
        ), patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "error", "error": "bad"},
        ):
            result = await FindymailNode.load_field_options(
                "lead_list_id",
                "user-1",
                {},
                credential_ids={"findymail": "cred-1"},
                pool=Mock(),
            )
        assert result == {"options": []}


class TestFindymailHelpers:
    def test_comma_list(self):
        assert _comma_list(None) is None
        assert _comma_list("a, b, ,c") == ["a", "b", "c"]

    def test_optional_int(self):
        assert _optional_int(None) is None
        assert _optional_int("12") == 12
        assert _optional_int("abc") is None

    def test_optional_bool(self):
        assert _optional_bool(None) is None
        assert _optional_bool("true") is True
        assert _optional_bool("false") is False

    def test_optional_int_list(self):
        assert _optional_int_list(None) is None
        assert _optional_int_list("1, 2, nope, 3") == [1, 2, 3]

    def test_build_icp_filters(self):
        config = Mock(
            icp_industries="Software, Biotechnology",
            icp_employee_count_ranges="51-200",
            icp_countries="US, FR",
            icp_job_title_keywords="VP Sales",
            icp_seniority_levels="11, 13",
        )
        assert _build_icp_filters(config) == {
            "industries": ["Software", "Biotechnology"],
            "employee_count_ranges": ["51-200"],
            "countries": ["US", "FR"],
            "job_title_keywords": ["VP Sales"],
            "seniority_levels": [11, 13],
        }

    def test_build_signal_monitor_payload(self):
        config = SimpleNamespace(
            name="Hiring Monitor",
            signal_type="company_hiring",
            keywords="hiring, fundraise",
            webhook_url="https://example.com/webhook",
            post_url=None,
            profile_url=None,
            engagement_types="like, comment",
            enrichment_level="email_phone",
            lead_list_id="42",
            ai_relevance_prompt="Focus on sales leadership",
            target_companies="acme.com, globex.com",
            is_shared="true",
            icp_industries="Software",
            icp_employee_count_ranges="51-200",
            icp_countries="US",
            icp_job_title_keywords="VP Sales",
            icp_seniority_levels="11,13",
            job_offer_title_keywords="sdr, ae",
            monitor_name=None,
        )
        assert _build_signal_monitor_payload(config, include_signal_type=True) == {
            "name": "Hiring Monitor",
            "signal_type": "company_hiring",
            "keywords": ["hiring", "fundraise"],
            "webhook_url": "https://example.com/webhook",
            "engagement_types": ["like", "comment"],
            "enrichment_level": "email_phone",
            "lead_list_id": 42,
            "ai_relevance_prompt": "Focus on sales leadership",
            "target_companies": ["acme.com", "globex.com"],
            "is_shared": True,
            "icp_filters": {
                "industries": ["Software"],
                "employee_count_ranges": ["51-200"],
                "countries": ["US"],
                "job_title_keywords": ["VP Sales"],
                "seniority_levels": [11, 13],
            },
            "job_offer_title_keywords": ["sdr", "ae"],
        }


class TestFindymailClassMethods:
    def test_get_config_model(self):
        assert FindymailNode.get_config_model() is FindymailNodeConfig

    @pytest.mark.asyncio
    async def test_register_external_webhook_requires_api_key(self):
        with pytest.raises(ValueError, match="API key is required"):
            await FindymailNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={},
                config={"signal_type": "job_change"},
                node_id="node-1",
            )

    @pytest.mark.asyncio
    async def test_register_external_webhook_surfaces_provider_error(self):
        with patch(
            "nodes.findymail_node._findymail_request",
            return_value={"status": "error", "error": "bad request"},
        ):
            with pytest.raises(ValueError, match="registration failed"):
                await FindymailNode._register_external_webhook(
                    webhook_url="https://abc.hooks.example.test",
                    credential={"api_key": "fm_test"},
                    config={"signal_type": "job_change"},
                    node_id="node-1",
                )

    @pytest.mark.asyncio
    async def test_unregister_external_webhook_without_api_key_or_external_id(self):
        with patch("nodes.findymail_node._findymail_request") as mock_req:
            await FindymailNode._unregister_external_webhook(
                credential={},
                config={},
                node_id="node-1",
            )
        mock_req.assert_not_called()

    def test_verify_webhook_signature_missing_header(self):
        assert not FindymailNode.verify_webhook_signature(
            b"{}", {}, {"signing_secret": "topsecret"}
        )
