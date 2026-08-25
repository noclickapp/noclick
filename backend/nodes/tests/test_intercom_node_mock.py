"""
Mock tests for the Intercom REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Contacts: create/update, get, update, list, search, archive, merge, note
- Conversations: create, get, list, search, reply, manage, tag
- Tickets: create, get, update, search
- Companies: create/update, get, list contacts
- Messaging: send message, submit data event
- Workspace: list tags, create tag, list admins, list teams, data attributes, segments
- Triggers: on_conversation_event, on_contact_event, on_ticket_event, on_company_event
- Error handling: API errors, missing credentials
- Dynamic options: admin & tag dropdowns
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.intercom_node import (
    IntercomNode,
    IntercomNodeConfig,
    IntercomAccessTokenCredential,
    IntercomCreateContactConfig,
    IntercomGetContactConfig,
    IntercomUpdateContactConfig,
    IntercomListContactsConfig,
    IntercomSearchContactsConfig,
    IntercomArchiveContactConfig,
    IntercomMergeContactsConfig,
    IntercomCreateNoteConfig,
    IntercomUnarchiveContactConfig,
    IntercomDeleteContactConfig,
    IntercomListContactNotesConfig,
    IntercomListContactCompaniesConfig,
    IntercomAttachContactToCompanyConfig,
    IntercomDetachContactFromCompanyConfig,
    IntercomTagContactConfig,
    IntercomUntagContactConfig,
    IntercomCreateConversationConfig,
    IntercomGetConversationConfig,
    IntercomListConversationsConfig,
    IntercomSearchConversationsConfig,
    IntercomReplyConversationConfig,
    IntercomManageConversationConfig,
    IntercomTagConversationConfig,
    IntercomUntagConversationConfig,
    IntercomCreateTicketConfig,
    IntercomGetTicketConfig,
    IntercomUpdateTicketConfig,
    IntercomSearchTicketsConfig,
    IntercomListTicketTypesConfig,
    IntercomReplyTicketConfig,
    IntercomCreateCompanyConfig,
    IntercomGetCompanyConfig,
    IntercomListCompanyContactsConfig,
    IntercomListCompaniesConfig,
    IntercomDeleteCompanyConfig,
    IntercomSendMessageConfig,
    IntercomSubmitEventConfig,
    IntercomListTagsConfig,
    IntercomCreateTagConfig,
    IntercomDeleteTagConfig,
    IntercomListAdminsConfig,
    IntercomListTeamsConfig,
    IntercomListDataAttributesConfig,
    IntercomListSegmentsConfig,
    IntercomListArticlesConfig,
    IntercomGetArticleConfig,
    IntercomCreateArticleConfig,
    IntercomUpdateArticleConfig,
    IntercomDeleteArticleConfig,
    IntercomConversationEventConfig,
    IntercomContactEventConfig,
    IntercomTicketEventConfig,
    IntercomCompanyEventConfig,
)


@pytest.fixture
def credentials():
    return IntercomAccessTokenCredential(access_token="dG9rZW46_test", region="us")


def create_intercom_node(config):
    return IntercomNode(
        node_id="test-intercom-node",
        node_type="automation-intercom",
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
    mock_response.text = "" if json_data is None else "{}"
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


async def _run(node, status_code=200, json_data=None):
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.intercom_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


class TestIntercomContactsMock:
    @pytest.mark.asyncio
    async def test_create_contact(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomCreateContactConfig(
                role="user", email="ada@example.com", name="Ada", custom_attributes='{"plan":"pro"}'
            ),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"type": "contact", "id": "c_1"})
        assert result["status"] == "success"
        assert result["action"] == "create_contact"
        assert result["data"]["id"] == "c_1"

    @pytest.mark.asyncio
    async def test_get_contact(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomGetContactConfig(contact_id="c_1"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"id": "c_1", "email": "a@b.com"})
        assert result["status"] == "success"
        assert result["action"] == "get_contact"
        assert result["data"]["id"] == "c_1"

    @pytest.mark.asyncio
    async def test_update_contact(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomUpdateContactConfig(contact_id="c_1", name="Ada L."),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "c_1", "name": "Ada L."})
        assert result["status"] == "success"
        assert result["action"] == "update_contact"

    @pytest.mark.asyncio
    async def test_list_contacts(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomListContactsConfig(per_page="50"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"type": "list", "data": [{"id": "c_1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_contacts"
        assert result["data"]["data"][0]["id"] == "c_1"

    @pytest.mark.asyncio
    async def test_search_contacts(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomSearchContactsConfig(
                query='{"field":"email","operator":"=","value":"a@b.com"}', per_page="20"
            ),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"type": "list", "data": []})
        assert result["status"] == "success"
        assert result["action"] == "search_contacts"

    @pytest.mark.asyncio
    async def test_archive_contact(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomArchiveContactConfig(contact_id="c_1"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"id": "c_1", "archived": True})
        assert result["status"] == "success"
        assert result["action"] == "archive_contact"

    @pytest.mark.asyncio
    async def test_merge_contacts(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomMergeContactsConfig(contact_id="lead_1", into_contact_id="user_1"),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "user_1"})
        assert result["status"] == "success"
        assert result["action"] == "merge_contacts"

    @pytest.mark.asyncio
    async def test_create_note(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomCreateNoteConfig(contact_id="c_1", body="Internal note", admin_id="a_1"),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "note_1", "type": "note"})
        assert result["status"] == "success"
        assert result["action"] == "create_note"


class TestIntercomConversationsMock:
    @pytest.mark.asyncio
    async def test_create_conversation(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomCreateConversationConfig(contact_id="c_1", body="Hi there"),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"conversation_id": "cv_1"})
        assert result["status"] == "success"
        assert result["action"] == "create_conversation"

    @pytest.mark.asyncio
    async def test_get_conversation(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomGetConversationConfig(conversation_id="cv_1"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"id": "cv_1", "open": True})
        assert result["status"] == "success"
        assert result["action"] == "get_conversation"
        assert result["data"]["id"] == "cv_1"

    @pytest.mark.asyncio
    async def test_list_conversations(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomListConversationsConfig(per_page="20"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"type": "conversation.list", "conversations": []})
        assert result["status"] == "success"
        assert result["action"] == "list_conversations"

    @pytest.mark.asyncio
    async def test_search_conversations(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomSearchConversationsConfig(
                query='{"field":"open","operator":"=","value":true}'
            ),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"conversations": []})
        assert result["status"] == "success"
        assert result["action"] == "search_conversations"

    @pytest.mark.asyncio
    async def test_reply_conversation_admin(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomReplyConversationConfig(
                conversation_id="cv_1", message_type="comment", reply_type="admin",
                body="Thanks!", admin_id="a_1",
            ),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "cv_1"})
        assert result["status"] == "success"
        assert result["action"] == "reply_conversation"

    @pytest.mark.asyncio
    async def test_manage_conversation(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomManageConversationConfig(
                conversation_id="cv_1", message_type="close", admin_id="a_1"
            ),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "cv_1", "state": "closed"})
        assert result["status"] == "success"
        assert result["action"] == "manage_conversation"

    @pytest.mark.asyncio
    async def test_tag_conversation(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomTagConversationConfig(conversation_id="cv_1", tag_id="t_1", admin_id="a_1"),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "t_1", "type": "tag"})
        assert result["status"] == "success"
        assert result["action"] == "tag_conversation"


class TestIntercomTicketsMock:
    @pytest.mark.asyncio
    async def test_create_ticket(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomCreateTicketConfig(
                ticket_type_id="tt_1", contact_id="c_1", title="Broken", description="It broke"
            ),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "tk_1", "type": "ticket"})
        assert result["status"] == "success"
        assert result["action"] == "create_ticket"
        assert result["data"]["id"] == "tk_1"

    @pytest.mark.asyncio
    async def test_get_ticket(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomGetTicketConfig(ticket_id="tk_1"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"id": "tk_1"})
        assert result["status"] == "success"
        assert result["action"] == "get_ticket"

    @pytest.mark.asyncio
    async def test_update_ticket(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomUpdateTicketConfig(ticket_id="tk_1", state="resolved", assignee_id="a_1"),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "tk_1", "state": "resolved"})
        assert result["status"] == "success"
        assert result["action"] == "update_ticket"

    @pytest.mark.asyncio
    async def test_search_tickets(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomSearchTicketsConfig(
                query='{"field":"state","operator":"=","value":"submitted"}'
            ),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"tickets": []})
        assert result["status"] == "success"
        assert result["action"] == "search_tickets"


class TestIntercomCompaniesMock:
    @pytest.mark.asyncio
    async def test_create_company(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomCreateCompanyConfig(company_id="co_1", name="Acme", plan="Enterprise"),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "comp_1", "name": "Acme"})
        assert result["status"] == "success"
        assert result["action"] == "create_company"

    @pytest.mark.asyncio
    async def test_get_company(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomGetCompanyConfig(company_id="comp_1"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"id": "comp_1"})
        assert result["status"] == "success"
        assert result["action"] == "get_company"

    @pytest.mark.asyncio
    async def test_list_company_contacts(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomListCompanyContactsConfig(company_id="comp_1"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"type": "list", "data": []})
        assert result["status"] == "success"
        assert result["action"] == "list_company_contacts"


class TestIntercomMessagingMock:
    @pytest.mark.asyncio
    async def test_send_message(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomSendMessageConfig(
                message_type="inapp", contact_id="c_1", admin_id="a_1", body="Welcome!"
            ),
            credentials=credentials,
        )
        result = await _run(create_intercom_node(config), 200, {"id": "msg_1", "type": "admin_message"})
        assert result["status"] == "success"
        assert result["action"] == "send_message"

    @pytest.mark.asyncio
    async def test_submit_event(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomSubmitEventConfig(
                event_name="purchased", email="a@b.com", metadata='{"amount":99}'
            ),
            credentials=credentials,
        )
        # /events returns 202 with empty body
        result = await _run(create_intercom_node(config), 202, None)
        assert result["status"] == "success"
        assert result["action"] == "submit_event"


class TestIntercomWorkspaceMock:
    @pytest.mark.asyncio
    async def test_list_tags(self, credentials):
        config = IntercomNodeConfig(config=IntercomListTagsConfig(), credentials=credentials)
        result = await _run(create_intercom_node(config), 200, {"type": "list", "data": [{"id": "t_1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_tags"

    @pytest.mark.asyncio
    async def test_create_tag(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomCreateTagConfig(name="VIP"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"id": "t_2", "name": "VIP"})
        assert result["status"] == "success"
        assert result["action"] == "create_tag"

    @pytest.mark.asyncio
    async def test_list_admins(self, credentials):
        config = IntercomNodeConfig(config=IntercomListAdminsConfig(), credentials=credentials)
        result = await _run(create_intercom_node(config), 200, {"type": "admin.list", "admins": [{"id": "a_1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_admins"

    @pytest.mark.asyncio
    async def test_list_teams(self, credentials):
        config = IntercomNodeConfig(config=IntercomListTeamsConfig(), credentials=credentials)
        result = await _run(create_intercom_node(config), 200, {"type": "team.list", "teams": []})
        assert result["status"] == "success"
        assert result["action"] == "list_teams"

    @pytest.mark.asyncio
    async def test_list_data_attributes(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomListDataAttributesConfig(model="contact"), credentials=credentials
        )
        result = await _run(create_intercom_node(config), 200, {"type": "list", "data": []})
        assert result["status"] == "success"
        assert result["action"] == "list_data_attributes"

    @pytest.mark.asyncio
    async def test_list_segments(self, credentials):
        config = IntercomNodeConfig(config=IntercomListSegmentsConfig(), credentials=credentials)
        result = await _run(create_intercom_node(config), 200, {"type": "segment.list", "segments": []})
        assert result["status"] == "success"
        assert result["action"] == "list_segments"


class TestIntercomTriggerMock:
    """Four decomposed domain triggers — each gets its own webhook URL."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cfg_cls, expected_action, topic",
        [
            (IntercomConversationEventConfig, "on_conversation_event", "conversation.user.created"),
            (IntercomContactEventConfig, "on_contact_event", "contact.user.created"),
            (IntercomTicketEventConfig, "on_ticket_event", "ticket.created"),
            (IntercomCompanyEventConfig, "on_company_event", "company.created"),
        ],
    )
    async def test_trigger_passthrough(self, cfg_cls, expected_action, topic):
        """Each domain trigger passes the inbound payload through as output."""
        config = IntercomNodeConfig(
            config=cfg_cls(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_intercom_node(config)
        payload = {"topic": topic, "data": {"item": {"id": "obj_1"}}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == expected_action
        assert result["data"]["topic"] == topic
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cfg_cls, event_type",
        [
            (IntercomConversationEventConfig, "conversation.admin.closed"),
            (IntercomContactEventConfig, "contact.archived"),
            (IntercomTicketEventConfig, "ticket.resolved"),
            (IntercomCompanyEventConfig, "company.deleted"),
        ],
    )
    async def test_trigger_echoes_selected_event_type(self, cfg_cls, event_type):
        """The trigger output echoes the selected event_types field."""
        config = IntercomNodeConfig(
            config=cfg_cls(webhook_url="https://abc.hooks.example.test", event_types=event_type),
            credentials=None,
        )
        node = create_intercom_node(config)
        result = await node.execute({"topic": event_type})
        assert result["status"] == "success"
        assert result["data"]["event_types"] == event_type

    def test_all_four_triggers_default_to_wildcard(self):
        """All domain triggers default to '*' (fire on any received topic)."""
        for cls in (
            IntercomConversationEventConfig,
            IntercomContactEventConfig,
            IntercomTicketEventConfig,
            IntercomCompanyEventConfig,
        ):
            assert cls().event_types == "*"

    def test_four_triggers_are_distinct_operations(self):
        """Each domain trigger has a unique operation literal."""
        ops = {
            IntercomConversationEventConfig().operation,
            IntercomContactEventConfig().operation,
            IntercomTicketEventConfig().operation,
            IntercomCompanyEventConfig().operation,
        }
        assert len(ops) == 4

    def test_verify_webhook_signature(self):
        secret = "client_secret_xyz"
        body = b'{"topic":"contact.user.created"}'
        good_sig = "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
        assert IntercomNode.verify_webhook_signature(
            body, {"x-hub-signature": good_sig}, {"signing_secret": secret}
        )
        assert not IntercomNode.verify_webhook_signature(
            body, {"x-hub-signature": "sha1=deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (verification not configured)
        assert IntercomNode.verify_webhook_signature(body, {}, {})


class TestIntercomTriggerEventFilterMock:
    """Runtime topic filtering shared by all four domain triggers.

    Each domain trigger has its own webhook URL and an independent topic
    subscription in Developer Hub, so only the relevant domain's topics
    arrive. Within a domain, event_types narrows to one specific topic.
    """

    def test_default_all_passes_every_topic(self):
        cfg = {"event_types": "*"}
        for topic in ("conversation.user.created", "ticket.created", "contact.user.updated"):
            assert IntercomNode.filter_trigger_payload({"topic": topic}, cfg) is True

    def test_unset_event_types_passes_every_topic(self):
        # No event_types stored (older configs) -> treated as "*".
        for topic in ("conversation.user.created", "ticket.created"):
            assert IntercomNode.filter_trigger_payload({"topic": topic}, {}) is True

    def test_selected_topic_passes(self):
        cfg = {"event_types": "conversation.user.created"}
        assert IntercomNode.filter_trigger_payload(
            {"topic": "conversation.user.created", "data": {"item": {"id": "cv_1"}}}, cfg
        ) is True

    def test_non_selected_topic_skipped(self):
        cfg = {"event_types": "conversation.user.created"}
        assert IntercomNode.filter_trigger_payload(
            {"topic": "ticket.created", "data": {"item": {"id": "tk_1"}}}, cfg
        ) is False
        assert IntercomNode.filter_trigger_payload(
            {"topic": "contact.user.created"}, cfg
        ) is False

    def test_ping_always_allowed(self):
        """The subscription health-check ping is never filtered out."""
        cfg = {"event_types": "conversation.user.created"}
        assert IntercomNode.filter_trigger_payload({"topic": "ping"}, cfg) is True

    def test_missing_topic_not_dropped(self):
        """A delivery we can't classify is processed rather than silently dropped."""
        cfg = {"event_types": "ticket.created"}
        assert IntercomNode.filter_trigger_payload({"data": {"item": {}}}, cfg) is True


class TestIntercomErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        config = IntercomNodeConfig(
            config=IntercomGetContactConfig(contact_id="missing"), credentials=credentials
        )
        node = create_intercom_node(config)
        result = await _run(
            node, 404, {"type": "error.list", "errors": [{"code": "not_found", "message": "Contact Not Found"}]}
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = IntercomNodeConfig(config=IntercomListTagsConfig(), credentials=None)
        node = create_intercom_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


class TestIntercomDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_admin_options(self):
        with patch(
            "nodes.intercom_node._intercom_request",
            return_value={
                "status": "success",
                "data": {"admins": [{"id": "a_1", "name": "Sam"}]},
            },
        ):
            result = await IntercomNode.load_field_options(
                "admin_id", credential_data={"access_token": "tok", "region": "us"}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "a_1"
        assert result["options"][0]["label"] == "Sam"

    @pytest.mark.asyncio
    async def test_load_tag_options(self):
        with patch(
            "nodes.intercom_node._intercom_request",
            return_value={
                "status": "success",
                "data": {"data": [{"id": "t_1", "name": "VIP"}]},
            },
        ):
            result = await IntercomNode.load_field_options(
                "tag_id", credential_data={"access_token": "tok", "region": "eu"}
            )
        assert result["options"][0]["value"] == "t_1"
        assert result["options"][0]["label"] == "VIP"


class TestIntercomContactsExtendedMock:
    @pytest.mark.asyncio
    async def test_unarchive_contact(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomUnarchiveContactConfig(contact_id="c_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "unarchive_contact", "data": {"id": "c_1", "archived": False}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "unarchive_contact"
        args, kwargs = mock_req.call_args
        assert args[2] == "POST"
        assert "/contacts/c_1/unarchive" in args[3]

    @pytest.mark.asyncio
    async def test_delete_contact(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomDeleteContactConfig(contact_id="c_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "delete_contact", "data": {"deleted": True}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_contact"
        args, kwargs = mock_req.call_args
        assert args[2] == "DELETE"
        assert "/contacts/c_1" in args[3]

    @pytest.mark.asyncio
    async def test_list_contact_notes(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomListContactNotesConfig(contact_id="c_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "list_contact_notes", "data": {"data": []}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_contact_notes"
        args, kwargs = mock_req.call_args
        assert args[2] == "GET"
        assert "/contacts/c_1/notes" in args[3]

    @pytest.mark.asyncio
    async def test_list_contact_companies(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomListContactCompaniesConfig(contact_id="c_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "list_contact_companies", "data": {"data": []}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_contact_companies"
        args, kwargs = mock_req.call_args
        assert args[2] == "GET"
        assert "/contacts/c_1/companies" in args[3]

    @pytest.mark.asyncio
    async def test_attach_contact_to_company(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomAttachContactToCompanyConfig(contact_id="c_1", company_id="comp_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "attach_contact_to_company", "data": {"id": "comp_1"}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "attach_contact_to_company"
        args, kwargs = mock_req.call_args
        assert args[2] == "POST"
        assert "/contacts/c_1/companies" in args[3]

    @pytest.mark.asyncio
    async def test_detach_contact_from_company(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomDetachContactFromCompanyConfig(contact_id="c_1", company_id="comp_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "detach_contact_from_company", "data": {}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "detach_contact_from_company"
        args, kwargs = mock_req.call_args
        assert args[2] == "DELETE"
        assert "/contacts/c_1/companies/comp_1" in args[3]

    @pytest.mark.asyncio
    async def test_tag_contact(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomTagContactConfig(contact_id="c_1", tag_id="t_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "tag_contact", "data": {"id": "t_1"}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "tag_contact"
        args, kwargs = mock_req.call_args
        assert args[2] == "POST"
        assert "/contacts/c_1/tags" in args[3]

    @pytest.mark.asyncio
    async def test_untag_contact(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomUntagContactConfig(contact_id="c_1", tag_id="t_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "untag_contact", "data": {}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "untag_contact"
        args, kwargs = mock_req.call_args
        assert args[2] == "DELETE"
        assert "/contacts/c_1/tags/t_1" in args[3]


class TestIntercomCompaniesExtendedMock:
    @pytest.mark.asyncio
    async def test_list_companies(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomListCompaniesConfig(per_page="50"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "list_companies", "data": {"data": []}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_companies"
        args, kwargs = mock_req.call_args
        assert args[2] == "GET"
        assert args[3] == "/companies"

    @pytest.mark.asyncio
    async def test_delete_company(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomDeleteCompanyConfig(company_id="comp_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "delete_company", "data": {"deleted": True}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_company"
        args, kwargs = mock_req.call_args
        assert args[2] == "DELETE"
        assert "/companies/comp_1" in args[3]


class TestIntercomConversationsExtendedMock:
    @pytest.mark.asyncio
    async def test_untag_conversation(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomUntagConversationConfig(conversation_id="cv_1", tag_id="t_1", admin_id="a_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "untag_conversation", "data": {}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "untag_conversation"
        args, kwargs = mock_req.call_args
        assert args[2] == "DELETE"
        assert "/conversations/cv_1/tags/t_1" in args[3]


class TestIntercomTicketsExtendedMock:
    @pytest.mark.asyncio
    async def test_list_ticket_types(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomListTicketTypesConfig(),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "list_ticket_types", "data": {"ticket_types": []}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_ticket_types"
        args, kwargs = mock_req.call_args
        assert args[2] == "GET"
        assert args[3] == "/ticket_types"

    @pytest.mark.asyncio
    async def test_reply_ticket(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomReplyTicketConfig(ticket_id="tk_1", message_type="comment", admin_id="a_1", body="Here is an update"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "reply_ticket", "data": {"id": "tk_1"}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "reply_ticket"
        args, kwargs = mock_req.call_args
        assert args[2] == "POST"
        assert "/tickets/tk_1/reply" in args[3]


class TestIntercomWorkspaceExtendedMock:
    @pytest.mark.asyncio
    async def test_delete_tag(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomDeleteTagConfig(tag_id="t_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "delete_tag", "data": {"deleted": True}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_tag"
        args, kwargs = mock_req.call_args
        assert args[2] == "DELETE"
        assert "/tags/t_1" in args[3]


class TestIntercomArticlesMock:
    @pytest.mark.asyncio
    async def test_list_articles(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomListArticlesConfig(per_page="20"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "list_articles", "data": {"data": []}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_articles"
        args, kwargs = mock_req.call_args
        assert args[2] == "GET"
        assert args[3] == "/articles"

    @pytest.mark.asyncio
    async def test_get_article(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomGetArticleConfig(article_id="art_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "get_article", "data": {"id": "art_1"}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_article"
        args, kwargs = mock_req.call_args
        assert args[2] == "GET"
        assert "/articles/art_1" in args[3]

    @pytest.mark.asyncio
    async def test_create_article(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomCreateArticleConfig(title="Getting Started", body="<p>Welcome!</p>", state="draft"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "create_article", "data": {"id": "art_2", "title": "Getting Started"}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_article"
        args, kwargs = mock_req.call_args
        assert args[2] == "POST"
        assert args[3] == "/articles"

    @pytest.mark.asyncio
    async def test_update_article(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomUpdateArticleConfig(article_id="art_1", title="Updated Title", state="published"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "update_article", "data": {"id": "art_1", "title": "Updated Title"}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_article"
        args, kwargs = mock_req.call_args
        assert args[2] == "PUT"
        assert "/articles/art_1" in args[3]

    @pytest.mark.asyncio
    async def test_delete_article(self, credentials):
        node = create_intercom_node(IntercomNodeConfig(
            config=IntercomDeleteArticleConfig(article_id="art_1"),
            credentials=credentials,
        ))
        with patch("nodes.intercom_node._intercom_request", return_value={"status": "success", "action": "delete_article", "data": {"deleted": True}}) as mock_req:
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_article"
        args, kwargs = mock_req.call_args
        assert args[2] == "DELETE"
        assert "/articles/art_1" in args[3]
