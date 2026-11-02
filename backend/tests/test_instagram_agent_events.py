"""An Instagram DM or comment reaches a wired agent as a turn of its own sender's
conversation, naming the ids its reply tools take.

Deliveries go through the same parser and trigger short-circuit a signed
webhook does. Fixture ids are synthetic: the repository is published.
"""

import json

import pytest

from nodes.instagram_node import InstagramNode
from utils import instagram_webhooks as ig

ACCOUNT = "123456789012345"
MEDIA = "423456789012345"
COMMENT = "523456789012345"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(ig, "current_time", lambda: 1788770000)


def deliver(entry, operation):
    events = ig.parse_instagram_webhook(json.dumps({"object": "instagram", "entry": [entry]}).encode())
    assert len(events) == 1
    return InstagramNode.resolve_trigger_payload(events[0][2], {"operation": operation})


def message(sender, mid, **body):
    return deliver({"id": ACCOUNT, "time": 1788770000, "messaging": [{
        "sender": {"id": sender}, "recipient": {"id": ACCOUNT}, "timestamp": 1788770000000,
        "message": {"mid": mid, **body}}]}, "on_message")


def comment(author_id, username, text="How much is shipping?"):
    author = {"username": username, **({"id": author_id} if author_id else {})}
    return deliver({"id": ACCOUNT, "time": 1788770000, "changes": [{"field": "comments", "value": {
        "id": COMMENT, "from": author, "media": {"id": MEDIA, "media_product_type": "FEED"},
        "text": text}}]}, "on_comment")


def test_each_dm_sender_gets_their_own_conversation():
    first = InstagramNode.resolve_agent_event(message("323456789012345", "mid.1", text="Do you ship to Leeds?"))
    second = InstagramNode.resolve_agent_event(message("333456789012345", "mid.2", text="Are you open Sunday?"))
    again = InstagramNode.resolve_agent_event(message("323456789012345", "mid.3", text="Thanks!"))

    assert first["conversation_key"] and second["conversation_key"]
    assert first["conversation_key"] != second["conversation_key"]
    assert again["conversation_key"] == first["conversation_key"]


def test_a_dm_turn_reads_as_the_message_with_its_reply_id():
    event = InstagramNode.resolve_agent_event(message("323456789012345", "mid.1", text="Do you ship to Leeds?"))

    assert "Do you ship to Leeds?" in event["text"]
    assert "send_dm" in event["text"] and "recipient_id=323456789012345" in event["text"]
    assert event["conversation_key"] == "instagram:323456789012345"


def test_a_dm_with_only_an_attachment_names_it():
    event = InstagramNode.resolve_agent_event(message(
        "323456789012345", "mid.1", attachments=[{"type": "image", "payload": {"url": "https://cdn.example.test/a.jpg"}}]))

    assert "image" in event["text"] and "https://cdn.example.test/a.jpg" in event["text"]
    assert event["conversation_key"] == "instagram:323456789012345"


def test_each_commenter_gets_their_own_conversation_and_the_comment_id():
    first = InstagramNode.resolve_agent_event(comment("343456789012345", "first_commenter"))
    second = InstagramNode.resolve_agent_event(comment("353456789012345", "second_commenter"))
    by_name = InstagramNode.resolve_agent_event(comment(None, "named_only"))

    assert len({first["conversation_key"], second["conversation_key"], by_name["conversation_key"]}) == 3
    assert "How much is shipping?" in first["text"]
    assert f"comment_id={COMMENT}" in first["text"] and "reply_to_comment" in first["text"]
    assert "@first_commenter" in first["text"]
    # A commenter's thread never shares a key with a DM sender's.
    assert not first["conversation_key"].startswith("instagram:3")


def test_a_mention_keeps_the_base_event():
    # On Mention executes the node with the credential; its output isn't a delivery the hook reads.
    output = {"status": "success", "action": "on_mention", "data": {"media_id": MEDIA}}
    assert InstagramNode.resolve_agent_event(output)["conversation_key"] is None


def test_the_agent_answers_in_the_senders_thread_not_its_chat_default():
    """The bug as it ran: the agent's own conversation key (its canvas chat) won
    for every Instagram sender, so all of them shared that one thread."""
    from nodes.agent.rehearsal import effective_conversation_key
    from nodes.agent_node import AgentNode

    agent = AgentNode(node_id="agent_1", node_type="agent", node_data={}, config=None,
                      sio=None, sid=None, workflow_id="wf")
    agent._workflow_nodes = [
        {"id": "ig", "type": "automation-instagram", "config": {"operation": "on_message", "_triggerPayload": {}}},
        {"id": "agent_1", "type": "agent", "config": {}},
    ]
    agent._workflow_edges = [{"source": "ig", "target": "agent_1"}]

    keys = set()
    for sender in ("323456789012345", "333456789012345"):
        event = agent._resolve_trigger_event({"ig": message(sender, f"mid.{sender}", text="Hello")})
        keys.add(effective_conversation_key(None, event["conversation_key"], "__interface_chat__"))
    assert keys == {"instagram:323456789012345", "instagram:333456789012345"}
