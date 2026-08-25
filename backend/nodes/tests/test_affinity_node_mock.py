"""
Mocked unit tests for Affinity CRM node.

Tests all 60 operations using mocked HTTP responses. No real Affinity
credentials required - all API calls are patched via AsyncMock.

Operations tested:
- System (2): get_whoami, get_rate_limit
- Persons (6): list_persons, get_person, create_person, update_person,
               delete_person, get_person_fields
- Organizations (6): list_organizations, get_organization, create_organization,
                     update_organization, delete_organization, get_organization_fields
- Opportunities (5): list_opportunities, get_opportunity, create_opportunity,
                     update_opportunity, delete_opportunity
- Lists (3): list_lists, get_list, create_list
- List Entries (4): list_list_entries, get_list_entry, create_list_entry, delete_list_entry
- Fields (3): list_fields, create_field, delete_field
- Field Values (5): list_field_values, create_field_value, update_field_value,
                    delete_field_value, list_field_value_changes
- Notes (5): list_notes, get_note, create_note, update_note, delete_note
- Reminders (5): list_reminders, get_reminder, create_reminder, update_reminder, delete_reminder
- Relationship Strengths (1): get_relationship_strengths
- Webhooks (5): list_webhooks, get_webhook, create_webhook, update_webhook, delete_webhook
- Files (4): list_files, get_file, download_file, upload_file
- v2 Companies (3): list_companies_v2, get_company_v2, list_company_fields_v2
- v2 List Entry Fields (3): list_list_fields_v2, get_list_entry_fields_v2,
                             update_list_entry_fields_v2

Run: pytest nodes/tests/test_affinity_node_mock.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch

from nodes.affinity_node import (
    AffinityNode,
    AffinityNodeConfig,
    AffinityAPIKeyCredential,
    # System
    AffinityGetWhoamiConfig,
    AffinityGetRateLimitConfig,
    # Persons
    AffinityListPersonsConfig,
    AffinityGetPersonConfig,
    AffinityCreatePersonConfig,
    AffinityUpdatePersonConfig,
    AffinityDeletePersonConfig,
    AffinityGetPersonFieldsConfig,
    # Organizations
    AffinityListOrganizationsConfig,
    AffinityGetOrganizationConfig,
    AffinityCreateOrganizationConfig,
    AffinityUpdateOrganizationConfig,
    AffinityDeleteOrganizationConfig,
    AffinityGetOrganizationFieldsConfig,
    # Opportunities
    AffinityListOpportunitiesConfig,
    AffinityGetOpportunityConfig,
    AffinityCreateOpportunityConfig,
    AffinityUpdateOpportunityConfig,
    AffinityDeleteOpportunityConfig,
    # Lists
    AffinityListListsConfig,
    AffinityGetListConfig,
    AffinityCreateListConfig,
    # List Entries
    AffinityListListEntriesConfig,
    AffinityGetListEntryConfig,
    AffinityCreateListEntryConfig,
    AffinityDeleteListEntryConfig,
    # Fields
    AffinityListFieldsConfig,
    AffinityCreateFieldConfig,
    AffinityDeleteFieldConfig,
    # Field Values
    AffinityListFieldValuesConfig,
    AffinityCreateFieldValueConfig,
    AffinityUpdateFieldValueConfig,
    AffinityDeleteFieldValueConfig,
    AffinityListFieldValueChangesConfig,
    # Notes
    AffinityListNotesConfig,
    AffinityGetNoteConfig,
    AffinityCreateNoteConfig,
    AffinityUpdateNoteConfig,
    AffinityDeleteNoteConfig,
    # Reminders
    AffinityListRemindersConfig,
    AffinityGetReminderConfig,
    AffinityCreateReminderConfig,
    AffinityUpdateReminderConfig,
    AffinityDeleteReminderConfig,
    # Relationship Strengths
    AffinityGetRelationshipStrengthsConfig,
    # Webhooks
    AffinityListWebhooksConfig,
    AffinityGetWebhookConfig,
    AffinityCreateWebhookConfig,
    AffinityUpdateWebhookConfig,
    AffinityDeleteWebhookConfig,
    # Files
    AffinityListFilesConfig,
    AffinityGetFileConfig,
    AffinityDownloadFileConfig,
    AffinityUploadFileConfig,
    # v2 Companies
    AffinityListCompaniesV2Config,
    AffinityGetCompanyV2Config,
    AffinityListCompanyFieldsV2Config,
    # v2 List Entry Fields
    AffinityListListFieldsV2Config,
    AffinityGetListEntryFieldsV2Config,
    AffinityUpdateListEntryFieldsV2Config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_CREDS = AffinityAPIKeyCredential(api_key="test_api_key_123")


def create_node(op_config) -> AffinityNode:
    """Create an AffinityNode with mock credentials."""
    node_config = AffinityNodeConfig(config=op_config, credentials=TEST_CREDS)
    return AffinityNode(
        node_id="test-node",
        node_type="automation-affinity",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )


def success_response(action: str, data: dict) -> dict:
    return {
        "status": "success",
        "action": action,
        "data": data,
        "status_code": 200,
        "timing_ms": {"api_request": 50.0},
    }


def deleted_response(action: str) -> dict:
    return {
        "status": "success",
        "action": action,
        "data": {"success": True},
        "status_code": 204,
        "timing_ms": {"api_request": 40.0},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAffinitySystemOps:
    @pytest.mark.asyncio
    async def test_get_whoami(self):
        expected = success_response(
            "get_authenticated_user_info", {"id": 1, "email": "user@example.com"}
        )
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetWhoamiConfig())
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_authenticated_user_info"
        mock.assert_called_once_with(
            "GET",
            "/auth/whoami",
            TEST_CREDS.api_key,
            action_name="get_authenticated_user_info",
        )

    @pytest.mark.asyncio
    async def test_get_rate_limit(self):
        expected = success_response(
            "get_rate_limit_info", {"month": {"remaining": 90000}}
        )
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetRateLimitConfig())
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_rate_limit_info"


class TestAffinityPersonOps:
    @pytest.mark.asyncio
    async def test_list_persons(self):
        expected = success_response("list_persons", {"persons": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListPersonsConfig(term="John", page_size=10))
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_persons"
        call_kwargs = mock.call_args
        assert call_kwargs.args[1] == "/persons"
        assert call_kwargs.kwargs["params"]["term"] == "John"

    @pytest.mark.asyncio
    async def test_get_person(self):
        expected = success_response("get_person_by_id", {"id": 42, "first_name": "Alice"})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetPersonConfig(person_id=42))
            result = await node.execute({})
        assert result["status"] == "success"
        mock.assert_called_once()
        assert "/persons/42" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_create_person(self):
        expected = success_response("create_person", {"id": 100})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreatePersonConfig(
                    first_name="Alice",
                    last_name="Smith",
                    emails="alice@example.com",
                )
            )
            result = await node.execute({})
        assert result["status"] == "success"
        body = mock.call_args.kwargs["json_body"]
        assert body["first_name"] == "Alice"
        assert body["last_name"] == "Smith"
        assert "alice@example.com" in body["emails"]

    @pytest.mark.asyncio
    async def test_create_person_with_org_ids(self):
        expected = success_response("create_person", {"id": 101})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreatePersonConfig(
                    first_name="Bob",
                    organization_ids="10, 20, 30",
                )
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["organization_ids"] == [10, 20, 30]

    @pytest.mark.asyncio
    async def test_update_person(self):
        expected = success_response("update_person", {"id": 42})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityUpdatePersonConfig(person_id=42, first_name="Alicia")
            )
            result = await node.execute({})
        assert result["status"] == "success"
        assert "PUT" == mock.call_args.args[0]

    @pytest.mark.asyncio
    async def test_delete_person(self):
        expected = deleted_response("delete_person")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeletePersonConfig(person_id=42))
            result = await node.execute({})
        assert result["status"] == "success"
        assert mock.call_args.args[0] == "DELETE"

    @pytest.mark.asyncio
    async def test_get_person_fields(self):
        expected = success_response("get_person_fields", {"fields": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetPersonFieldsConfig())
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/persons/fields" in mock.call_args.args[1]


class TestAffinityOrganizationOps:
    @pytest.mark.asyncio
    async def test_list_organizations(self):
        expected = success_response("list_organizations", {"organizations": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListOrganizationsConfig(term="Acme"))
            result = await node.execute({})
        assert result["status"] == "success"
        assert mock.call_args.kwargs["params"]["term"] == "Acme"

    @pytest.mark.asyncio
    async def test_get_organization(self):
        expected = success_response("get_organization", {"id": 99, "name": "Acme"})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetOrganizationConfig(organization_id=99))
            result = await node.execute({})
        assert "/organizations/99" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_create_organization(self):
        expected = success_response("create_organization", {"id": 200})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateOrganizationConfig(name="Acme Corp", domain="acme.com")
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["name"] == "Acme Corp"
        assert body["domain"] == "acme.com"

    @pytest.mark.asyncio
    async def test_update_organization(self):
        expected = success_response("update_organization", {"id": 99})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityUpdateOrganizationConfig(organization_id=99, name="Acme Inc")
            )
            result = await node.execute({})
        assert mock.call_args.args[0] == "PUT"

    @pytest.mark.asyncio
    async def test_delete_organization(self):
        expected = deleted_response("delete_organization")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeleteOrganizationConfig(organization_id=99))
            result = await node.execute({})
        assert mock.call_args.args[0] == "DELETE"

    @pytest.mark.asyncio
    async def test_get_organization_fields(self):
        expected = success_response("get_organization_fields", {"fields": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetOrganizationFieldsConfig())
            result = await node.execute({})
        assert "/organizations/fields" in mock.call_args.args[1]


class TestAffinityOpportunityOps:
    @pytest.mark.asyncio
    async def test_list_opportunities(self):
        expected = success_response("list_opportunities", {"opportunities": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListOpportunitiesConfig())
            result = await node.execute({})
        assert result["action"] == "list_opportunities"

    @pytest.mark.asyncio
    async def test_get_opportunity(self):
        expected = success_response("get_opportunity_by_id", {"id": 5, "name": "Deal X"})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetOpportunityConfig(opportunity_id=5))
            result = await node.execute({})
        assert "/opportunities/5" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_create_opportunity(self):
        expected = success_response("create_opportunity", {"id": 300})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateOpportunityConfig(name="Big Deal", list_id=7)
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["name"] == "Big Deal"
        assert body["list_id"] == 7

    @pytest.mark.asyncio
    async def test_update_opportunity(self):
        expected = success_response("update_opportunity", {"id": 5})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityUpdateOpportunityConfig(opportunity_id=5, name="Updated")
            )
            result = await node.execute({})
        assert mock.call_args.args[0] == "PUT"

    @pytest.mark.asyncio
    async def test_delete_opportunity(self):
        expected = deleted_response("delete_opportunity")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeleteOpportunityConfig(opportunity_id=5))
            result = await node.execute({})
        assert mock.call_args.args[0] == "DELETE"


class TestAffinityListOps:
    @pytest.mark.asyncio
    async def test_list_lists(self):
        expected = success_response("list_lists", {"lists": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListListsConfig())
            result = await node.execute({})
        assert mock.call_args.args[1] == "/lists"

    @pytest.mark.asyncio
    async def test_get_list(self):
        expected = success_response("get_list_by_id", {"id": 3, "name": "Prospects"})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetListConfig(list_id=3))
            result = await node.execute({})
        assert "/lists/3" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_create_list(self):
        expected = success_response("create_list", {"id": 10})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityCreateListConfig(name="New List", type="1"))
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["name"] == "New List"
        assert body["type"] == 1


class TestAffinityListEntryOps:
    @pytest.mark.asyncio
    async def test_list_list_entries(self):
        expected = success_response("list_list_entries", {"list_entries": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListListEntriesConfig(list_id=3))
            result = await node.execute({})
        assert "/lists/3/list-entries" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_get_list_entry(self):
        expected = success_response("get_list_entry", {"id": 55})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetListEntryConfig(list_id=3, entry_id=55))
            result = await node.execute({})
        assert "/lists/3/list-entries/55" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_create_list_entry(self):
        expected = success_response("create_list_entry", {"id": 66})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityCreateListEntryConfig(list_id=3, entity_id=99))
            result = await node.execute({})
        assert mock.call_args.kwargs["json_body"]["entity_id"] == 99

    @pytest.mark.asyncio
    async def test_delete_list_entry(self):
        expected = deleted_response("delete_list_entry")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeleteListEntryConfig(list_id=3, entry_id=55))
            result = await node.execute({})
        assert mock.call_args.args[0] == "DELETE"
        assert "/lists/3/list-entries/55" in mock.call_args.args[1]


class TestAffinityFieldOps:
    @pytest.mark.asyncio
    async def test_list_fields(self):
        expected = success_response("list_fields", {"fields": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListFieldsConfig())
            result = await node.execute({})
        assert mock.call_args.args[1] == "/fields"

    @pytest.mark.asyncio
    async def test_create_field(self):
        expected = success_response("create_custom_field", {"id": 77})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateFieldConfig(
                    name="Revenue", entity_type="1", value_type="3"
                )
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["name"] == "Revenue"
        assert body["entity_type"] == 1
        assert body["value_type"] == 3

    @pytest.mark.asyncio
    async def test_create_field_allows_multiple(self):
        expected = success_response("create_custom_field", {"id": 78})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateFieldConfig(
                    name="Tags", entity_type="0", value_type="2", allows_multiple="true"
                )
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["allows_multiple"] is True

    @pytest.mark.asyncio
    async def test_delete_field(self):
        expected = deleted_response("delete_custom_field")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeleteFieldConfig(field_id=77))
            result = await node.execute({})
        assert "/fields/77" in mock.call_args.args[1]


class TestAffinityFieldValueOps:
    @pytest.mark.asyncio
    async def test_list_field_values(self):
        expected = success_response("list_field_values", {"field_values": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListFieldValuesConfig(person_id=42))
            result = await node.execute({})
        assert mock.call_args.kwargs["params"]["person_id"] == 42

    @pytest.mark.asyncio
    async def test_create_field_value_string(self):
        expected = success_response("create_field_value", {"id": 111})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateFieldValueConfig(field_id=5, entity_id=42, value="hello")
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["value"] == "hello"

    @pytest.mark.asyncio
    async def test_create_field_value_json(self):
        expected = success_response("create_field_value", {"id": 112})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateFieldValueConfig(
                    field_id=5, entity_id=42, value='{"nested": true}'
                )
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["value"] == {"nested": True}

    @pytest.mark.asyncio
    async def test_update_field_value(self):
        expected = success_response("update_field_value", {"id": 111})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityUpdateFieldValueConfig(field_value_id=111, value="new")
            )
            result = await node.execute({})
        assert mock.call_args.args[0] == "PUT"
        assert "/field-values/111" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_delete_field_value(self):
        expected = deleted_response("delete_field_value")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeleteFieldValueConfig(field_value_id=111))
            result = await node.execute({})
        assert "/field-values/111" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_list_field_value_changes(self):
        expected = success_response("list_field_value_changes", {"changes": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListFieldValueChangesConfig(field_id=5))
            result = await node.execute({})
        assert "/field-value-changes" in mock.call_args.args[1]
        assert mock.call_args.kwargs["params"]["field_id"] == 5


class TestAffinityNoteOps:
    @pytest.mark.asyncio
    async def test_list_notes(self):
        expected = success_response("list_notes", {"notes": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListNotesConfig(person_id=42))
            result = await node.execute({})
        assert mock.call_args.kwargs["params"]["person_id"] == 42

    @pytest.mark.asyncio
    async def test_get_note(self):
        expected = success_response("get_note_by_id", {"id": 9, "content": "Hi"})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetNoteConfig(note_id=9))
            result = await node.execute({})
        assert "/notes/9" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_create_note(self):
        expected = success_response("create_note", {"id": 50})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateNoteConfig(
                    content="Meeting notes",
                    person_ids="1, 2",
                    organization_ids="10",
                )
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["content"] == "Meeting notes"
        assert body["person_ids"] == [1, 2]
        assert body["organization_ids"] == [10]

    @pytest.mark.asyncio
    async def test_update_note(self):
        expected = success_response("update_note", {"id": 9})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityUpdateNoteConfig(note_id=9, content="Updated"))
            result = await node.execute({})
        assert mock.call_args.args[0] == "PUT"
        assert mock.call_args.kwargs["json_body"]["content"] == "Updated"

    @pytest.mark.asyncio
    async def test_delete_note(self):
        expected = deleted_response("delete_note")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeleteNoteConfig(note_id=9))
            result = await node.execute({})
        assert "/notes/9" in mock.call_args.args[1]
        assert mock.call_args.args[0] == "DELETE"


class TestAffinityReminderOps:
    @pytest.mark.asyncio
    async def test_list_reminders(self):
        expected = success_response("list_reminders", {"reminders": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListRemindersConfig(owner_id=1))
            result = await node.execute({})
        assert mock.call_args.kwargs["params"]["owner_id"] == 1

    @pytest.mark.asyncio
    async def test_get_reminder(self):
        expected = success_response("get_reminder_by_id", {"id": 7})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetReminderConfig(reminder_id=7))
            result = await node.execute({})
        assert "/reminders/7" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_create_reminder(self):
        expected = success_response("create_reminder", {"id": 88})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateReminderConfig(
                    content="Follow up",
                    due_date="2025-01-01T12:00:00Z",
                    person_ids="42",
                )
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["content"] == "Follow up"
        assert body["due_date"] == "2025-01-01T12:00:00Z"
        assert body["person_ids"] == [42]

    @pytest.mark.asyncio
    async def test_update_reminder(self):
        expected = success_response("update_reminder", {"id": 7})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityUpdateReminderConfig(
                    reminder_id=7, completed_at="2025-01-02T08:00:00Z"
                )
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["completed_at"] == "2025-01-02T08:00:00Z"

    @pytest.mark.asyncio
    async def test_delete_reminder(self):
        expected = deleted_response("delete_reminder")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeleteReminderConfig(reminder_id=7))
            result = await node.execute({})
        assert "/reminders/7" in mock.call_args.args[1]


class TestAffinityRelationshipStrengths:
    @pytest.mark.asyncio
    async def test_get_relationship_strengths(self):
        expected = success_response(
            "get_relationship_strengths", {"strengths": [{"score": 95}]}
        )
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityGetRelationshipStrengthsConfig(internal_id=1, external_id=42)
            )
            result = await node.execute({})
        params = mock.call_args.kwargs["params"]
        assert params["internal_id"] == 1
        assert params["external_id"] == 42


class TestAffinityWebhookOps:
    @pytest.mark.asyncio
    async def test_list_webhooks(self):
        expected = success_response("list_webhooks", {"webhook_subscriptions": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListWebhooksConfig())
            result = await node.execute({})
        assert "/webhook-subscriptions" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_get_webhook(self):
        expected = success_response("get_webhook", {"id": 2})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetWebhookConfig(webhook_id=2))
            result = await node.execute({})
        assert "/webhook-subscriptions/2" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_create_webhook(self):
        expected = success_response("create_webhook", {"id": 3})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityCreateWebhookConfig(
                    webhook_url="https://example.com/hook",
                    subscriptions='[{"type": 0, "triggers": [1]}]',
                )
            )
            result = await node.execute({})
        body = mock.call_args.kwargs["json_body"]
        assert body["webhook_url"] == "https://example.com/hook"
        assert isinstance(body["subscriptions"], list)

    @pytest.mark.asyncio
    async def test_update_webhook(self):
        expected = success_response("update_webhook", {"id": 2})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityUpdateWebhookConfig(
                    webhook_id=2, webhook_url="https://example.com/new"
                )
            )
            result = await node.execute({})
        assert mock.call_args.args[0] == "PUT"

    @pytest.mark.asyncio
    async def test_delete_webhook(self):
        expected = deleted_response("delete_webhook")
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDeleteWebhookConfig(webhook_id=2))
            result = await node.execute({})
        assert mock.call_args.args[0] == "DELETE"


class TestAffinityFileOps:
    @pytest.mark.asyncio
    async def test_list_files(self):
        expected = success_response("list_files", {"files": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListFilesConfig(organization_id=99))
            result = await node.execute({})
        assert mock.call_args.kwargs["params"]["organization_id"] == 99

    @pytest.mark.asyncio
    async def test_get_file(self):
        expected = success_response("get_file", {"id": 15, "name": "report.pdf"})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetFileConfig(file_id=15))
            result = await node.execute({})
        assert "/files/15" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_download_file(self):
        expected = success_response(
            "download_file", {"download_url": "https://s3.amazonaws.com/..."}
        )
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityDownloadFileConfig(file_id=15))
            result = await node.execute({})
        assert "/files/15/download" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_upload_file(self):
        """upload_file uses its own httpx logic; mock _handle_upload_file instead."""
        expected = {
            "status": "success",
            "action": "upload_file",
            "data": {"id": 20},
            "status_code": 200,
            "timing_ms": {"api_request": 200.0},
        }
        with patch.object(
            AffinityNode, "_handle_upload_file", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityUploadFileConfig(
                    file_url="https://example.com/doc.pdf",
                    file_name="doc.pdf",
                    person_id=42,
                )
            )
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upload_file"


class TestAffinityV2CompanyOps:
    @pytest.mark.asyncio
    async def test_list_companies_v2(self):
        expected = success_response("list_companies", {"data": [], "pagination": {}})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListCompaniesV2Config(limit=50))
            result = await node.execute({})
        assert mock.call_args.args[1] == "/v2/companies"
        assert mock.call_args.kwargs["params"]["limit"] == 50

    @pytest.mark.asyncio
    async def test_get_company_v2(self):
        expected = success_response("get_company_by_id", {"id": 123, "name": "Acme"})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityGetCompanyV2Config(company_id=123))
            result = await node.execute({})
        assert "/v2/companies/123" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_list_company_fields_v2(self):
        expected = success_response("list_company_fields", {"data": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListCompanyFieldsV2Config(company_id=123))
            result = await node.execute({})
        assert "/v2/companies/123/fields" in mock.call_args.args[1]


class TestAffinityV2ListEntryFieldOps:
    @pytest.mark.asyncio
    async def test_list_list_fields_v2(self):
        expected = success_response("list_list_fields", {"data": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListListFieldsV2Config(list_id=3))
            result = await node.execute({})
        assert "/v2/lists/3/fields" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_get_list_entry_fields_v2(self):
        expected = success_response("get_list_entry_fields", {"data": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityGetListEntryFieldsV2Config(list_id=3, entry_id=55)
            )
            result = await node.execute({})
        assert "/v2/lists/3/list-entries/55/fields" in mock.call_args.args[1]

    @pytest.mark.asyncio
    async def test_update_list_entry_fields_v2(self):
        expected = success_response("update_list_entry_fields", {"data": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(
                AffinityUpdateListEntryFieldsV2Config(
                    list_id=3,
                    entry_id=55,
                    fields='[{"id": 10, "value": "new"}]',
                )
            )
            result = await node.execute({})
        assert mock.call_args.args[0] == "PATCH"
        body = mock.call_args.kwargs["json_body"]
        assert isinstance(body["fields"], list)
        assert body["fields"][0]["id"] == 10


class TestAffinityAuthHeaders:
    """Verify correct auth header generation for v1 vs v2 endpoints."""

    def test_v1_endpoint_uses_basic_auth(self):
        import base64

        node = create_node(AffinityGetWhoamiConfig())
        header = node._get_auth_header("mykey", "/auth/whoami")
        expected = "Basic " + base64.b64encode(b":mykey").decode()
        assert header == expected

    def test_v2_endpoint_uses_bearer_auth(self):
        node = create_node(AffinityGetWhoamiConfig())
        header = node._get_auth_header("mykey", "/v2/companies")
        assert header == "Bearer mykey"


class TestAffinityErrorHandling:
    @pytest.mark.asyncio
    async def test_error_response_propagated(self):
        error_response = {
            "status": "error",
            "action": "list_persons",
            "error": "Unauthorized",
            "status_code": 401,
            "timing_ms": {"api_request": 20.0},
        }
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = error_response
            node = create_node(AffinityListPersonsConfig())
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["error"] == "Unauthorized"
        assert result["status_code"] == 401

    @pytest.mark.asyncio
    async def test_timing_total_added(self):
        expected = success_response("list_lists", {"lists": []})
        with patch.object(
            AffinityNode, "_make_request", new_callable=AsyncMock
        ) as mock:
            mock.return_value = expected
            node = create_node(AffinityListListsConfig())
            result = await node.execute({})
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["total"] >= 0

    @pytest.mark.asyncio
    async def test_unknown_action_raises(self):
        node = create_node(AffinityGetWhoamiConfig())
        # Manually corrupt the action
        node._config.config.operation = "nonexistent_action"  # type: ignore
        with pytest.raises(ValueError, match="Unknown Affinity action"):
            await node.execute({})
