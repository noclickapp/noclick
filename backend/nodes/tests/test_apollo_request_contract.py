"""Request regressions from https://docs.apollo.io/openapi/apollo-rest-api.json.

Inspect request arguments without inventing provider responses. Workflow field
names stay stable while the wire format follows Apollo's published contract.
"""
from unittest.mock import AsyncMock, Mock

import pytest

from nodes.apollo_node import ApolloNode, ApolloNodeConfig


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,method,endpoint,location,expected",
    [
        ({"operation": "create_deal", "name": "Demo", "deal_stage_id": "stage"},
         "POST", "/opportunities", "json_body", {"name": "Demo", "opportunity_stage_id": "stage"}),
        ({"operation": "list_deals"}, "GET", "/opportunities/search", "params", {"page": 1, "per_page": 25}),
        ({"operation": "get_deal_details", "deal_id": "deal"}, "GET", "/opportunities/deal", None, None),
        ({"operation": "update_deal_details", "deal_id": "deal", "deal_stage_id": "stage", "amount": 0},
         "PATCH", "/opportunities/deal", "json_body", {"opportunity_stage_id": "stage", "amount": "0.0"}),
        ({"operation": "create_multiple_accounts", "accounts": [{"name": "Apollo"}]},
         "POST", "/accounts/bulk_create", "json_body", {"accounts": [{"name": "Apollo"}]}),
        ({"operation": "update_multiple_accounts", "accounts": [{"id": "account", "name": "Apollo"}]},
         "POST", "/accounts/bulk_update", "json_body", {"account_attributes": [{"id": "account", "name": "Apollo"}]}),
        ({"operation": "update_account_stage_bulk", "account_ids": ["one", "two"], "account_stage_id": "stage"},
         "POST", "/accounts/bulk_update", "json_body", {"account_ids": ["one", "two"], "account_stage_id": "stage"}),
        ({"operation": "update_account_ownership", "account_ids": ["one", "two"], "owner_id": "owner"},
         "POST", "/accounts/update_owners", "params", {"account_ids[]": ["one", "two"], "owner_id": "owner"}),
        ({"operation": "create_multiple_contacts", "contacts": [{"first_name": "Jordan"}]},
         "POST", "/contacts/bulk_create", "json_body", {"contacts": [{"first_name": "Jordan"}]}),
        ({"operation": "update_multiple_contacts", "contacts": [{"id": "contact", "first_name": "Jordan"}]},
         "POST", "/contacts/bulk_update", "json_body", {"contact_attributes": [{"id": "contact", "first_name": "Jordan"}]}),
        ({"operation": "update_contact_stage_bulk", "contact_ids": ["one", "two"], "contact_stage_id": "stage"},
         "POST", "/contacts/update_stages", "params", {"contact_ids[]": ["one", "two"], "contact_stage_id": "stage"}),
        ({"operation": "update_contact_ownership", "contact_ids": ["one", "two"], "owner_id": "owner"},
         "POST", "/contacts/update_owners", "params", {"contact_ids[]": ["one", "two"], "owner_id": "owner"}),
        ({"operation": "search_organization_news_articles", "organization_ids": ["one", "two"]},
         "POST", "/news_articles/search", "params", {"organization_ids[]": ["one", "two"], "page": 1, "per_page": 25}),
        ({"operation": "add_contacts_to_outreach_sequence", "sequence_id": "sequence", "contact_ids": ["one", "two"],
          "send_email_from_email_account_id": "sender"},
         "POST", "/emailer_campaigns/sequence/add_contact_ids", "params",
         {"emailer_campaign_id": "sequence", "contact_ids[]": ["one", "two"], "send_email_from_email_account_id": "sender"}),
        ({"operation": "search_outreach_sequences", "q_name": "Demo"},
         "POST", "/emailer_campaigns/search", "params", {"q_name": "Demo"}),
        ({"operation": "enrich_single_person", "email": "jordan@ymail.com"},
         "POST", "/people/match", "params", {"email": "jordan@ymail.com", "reveal_personal_emails": False, "reveal_phone_number": False}),
        ({"operation": "enrich_multiple_organizations", "domains": ["apollo.io", "microsoft.com"]},
         "POST", "/organizations/bulk_enrich", "params", {"domains[]": ["apollo.io", "microsoft.com"]}),
        ({"operation": "search_people_in_apollo", "person_titles": ["CEO"], "organization_domains": ["apollo.io"]},
         "POST", "/mixed_people/api_search", "params",
         {"person_titles[]": ["CEO"], "q_organization_domains_list[]": ["apollo.io"], "page": 1, "per_page": 25}),
        ({"operation": "search_organizations_in_apollo", "organization_locations": ["Ireland"]},
         "POST", "/mixed_companies/search", "params", {"organization_locations[]": ["Ireland"], "page": 1, "per_page": 25}),
        ({"operation": "update_contact_sequence_status", "contact_id": "contact", "sequence_id": "sequence", "status": "finished"},
         "POST", "/emailer_campaigns/remove_or_stop_contact_ids", "params",
         {"contact_ids[]": ["contact"], "emailer_campaign_ids[]": ["sequence"], "mode": "mark_as_finished"}),
        ({"operation": "create_custom_field", "name": "Test Name", "field_type": "contact", "widget_type": "text"},
         "POST", "/fields", "json_body", {"label": "Test Name", "modality": "contact", "type": "string"}),
        ({"operation": "get_api_usage_and_limits"}, "POST", "/usage_stats/api_usage_stats", "json_body", {}),
        ({"operation": "create_task", "contact_id": "contact", "user_id": "owner", "due_at": "2025-02-15T08:10:30Z", "type": "email"},
         "POST", "/tasks", "json_body", {"contact_id": "contact", "user_id": "owner", "due_at": "2025-02-15T08:10:30Z",
                                            "status": "scheduled", "type": "outreach_manual_email", "priority": "medium"}),
    ],
)
async def test_documented_request_arguments(config, method, endpoint, location, expected):
    node = ApolloNode(
        node_id="contract", node_type="automation-apollo", node_data={}, sio=Mock(),
        config=ApolloNodeConfig(config=config, credentials={"credential_type": "apollo_api_key", "api_key": "fake"}),
    )
    node._make_request = AsyncMock(return_value={"timing_ms": {}})
    await node.execute({})
    node._make_request.assert_awaited_once()
    request = node._make_request.call_args.kwargs
    assert request["method"] == method
    assert request["endpoint"] == endpoint
    if location:
        assert request[location] == expected
        assert ("json_body" if location == "params" else "params") not in request


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "update_contact_sequence_status", "contact_id": "contact", "sequence_id": "sequence", "status": "active"},
        {"operation": "create_custom_field", "name": "Test Name", "field_type": "contact", "widget_type": "dropdown"},
    ],
)
def test_rejects_undocumented_statuses_and_widgets(config):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ApolloNodeConfig(config=config, credentials={"credential_type": "apollo_api_key", "api_key": "fake"})
