"""WhatsApp groups on a QR-linked number (``utils.wahooks_groups`` + the WhatsApp node's group operations), with
WAHooks' group routes faked over HTTP: each operation calls its route with NoClick's key, answers what an agent
relays plainly (who was added, who wasn't and why), and says a refusal in words; the operations are agent tools
like any other, a group made is one a scoped tool may then act on, and a group's turn names its members, capped."""

import json
from typing import Any, Dict, List

import httpx
import pytest

from nodes.whatsapp_node import (
    NOCLICK_LINE_IN_GROUP, WhatsAppAddGroupParticipantsConfig, WhatsAppNode, WhatsAppNodeConfig,
    WhatsAppQRCredential,
)
from utils import wahooks_connections, wahooks_groups

# Only the reviewed fictional WhatsApp ids (scripts/check-community-boundary.sh in the open edition).
LINE = "conn-groups-1"
GROUP = "120000000000000001@g.us"
ME = {"id": "12025550108@c.us", "phone": "12025550108", "lid": None, "name": "12025550108", "role": "superadmin",
      "isMe": True}
ASHA = {"id": "12025550101@c.us", "phone": "12025550101", "lid": None, "name": "Asha", "role": "admin",
        "isMe": False}
KIT = {"id": "12025550102@lid", "phone": None, "lid": "12025550102@lid", "name": None, "role": "member",
       "isMe": False}


def _group(*members: Dict[str, Any], name: str = "Bakery orders", me: Dict[str, Any] = ME) -> Dict[str, Any]:
    return {"id": GROUP, "name": name, "description": "Orders for the week", "owner": me["id"], "createdAt": None,
            "participantCount": len(members) + 1, "participants": [me, *members], "announcementOnly": False,
            "locked": True, "isCommunity": False}


class FakeGroups:
    """WAHooks' group routes: each request recorded as (method, path, query, body); ``answers`` maps a
    ``"METHOD /path-suffix"`` to its (status, body), else 404."""

    def __init__(self) -> None:
        self.requests: List[tuple] = []
        self.answers: Dict[str, tuple] = {}
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer wh_test"
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix(f"/api/connections/{LINE}")
        self.requests.append((request.method, path, dict(request.url.params), body))
        if self.down:
            raise httpx.ConnectError("unreachable", request=request)
        status, answer = self.answers.get(f"{request.method} {path}", (404, {"message": "Group not found"}))
        return httpx.Response(status, json=answer)


@pytest.fixture
def wahooks(monkeypatch):
    fake = FakeGroups()
    transport = httpx.MockTransport(fake.handle)
    monkeypatch.setenv("WAHOOKS_API_KEY", "wh_test")
    monkeypatch.setattr(wahooks_connections, "wahooks_http", lambda key, **kw: httpx.AsyncClient(
        base_url="https://api.wahooks.com/api", transport=transport, headers={"Authorization": f"Bearer {key}"}))
    return fake


def _node(config) -> WhatsAppNode:
    return WhatsAppNode(node_id="wa", node_type="automation-whatsapp", node_data={},
                        config=WhatsAppNodeConfig(config=config, credentials=WhatsAppQRCredential(connection_id=LINE)),
                        sio=None, sid=None, workflow_id="wf-1")


async def _tool(operation: str, **arguments) -> Dict[str, Any]:
    """A call as an agent's tool makes it: the graph-free operation seam, on the QR credential."""
    from nodes.core.run_op import run_node_operation

    return await run_node_operation(node_type="automation-whatsapp", operation=operation, arguments=arguments,
                                    user_id="user-1", credential_data={"credential_type": "whatsapp_qr",
                                                                       "connection_id": LINE})


async def test_get_group_reads_who_is_in_it_and_whether_you_are_an_admin(wahooks):
    wahooks.answers[f"GET /groups/{GROUP}"] = (200, _group(KIT, ASHA))
    out = await _tool("get_group", group_id=GROUP, refresh="true")
    assert out["status"] == "success" and out["provider"] == "wahooks"
    assert wahooks.requests == [("GET", f"/groups/{GROUP}", {"refresh": "true"}, None)]
    assert out["data"] == {
        "group_id": GROUP, "name": "Bakery orders", "description": "Orders for the week", "member_count": 3,
        "you_are_admin": True, "only_admins_send": False, "only_admins_edit": True, "is_community": False,
        # Admins first, the account itself left out, a hidden number named as none.
        "members": [{"id": ASHA["id"], "name": "Asha", "phone": "+1 202-555-0101", "role": "admin"},
                    {"id": KIT["id"], "name": None, "phone": None, "role": "member"}]}


async def test_create_group_says_who_was_added_and_who_wasnt_and_why(wahooks):
    made = {**_group(ASHA, name="Weekend trek"), "notAdded": [
        {"id": "12025550100@s.whatsapp.net", "phone": "12025550100", "lid": None, "status": "failed", "code": 403,
         "reason": "privacy"},
        {"id": "12025550104@s.whatsapp.net", "phone": "12025550104", "lid": None, "status": "failed", "code": 404,
         "reason": "not on WhatsApp"}]}
    wahooks.answers["POST /groups"] = (201, made)
    out = await _tool("create_group", name="Weekend trek",
                      participants="+1 202-555-0101, 12025550100\n+12025550104")
    assert out["status"] == "success"
    assert wahooks.requests[0][3] == {"name": "Weekend trek",
                                      "participants": ["12025550101", "12025550100", "12025550104"]}
    data = out["data"]
    assert data["group_id"] == GROUP and [m["name"] for m in data["members"]] == ["Asha"]
    assert data["not_added"][0] == {
        "who": "+1 202-555-0100", "id": "12025550100@s.whatsapp.net", "outcome": "not added",
        "why": "their privacy settings let only their contacts add them to groups: send them the group's invite link"}
    assert data["summary"] == (
        f'Created the group "Weekend trek" ({GROUP}). In it besides you: Asha (+1 202-555-0101, admin). Not added: '
        "+1 202-555-0100 (their privacy settings let only their contacts add them to groups: send them the group's "
        "invite link); +1 202-555-0104 (that number isn't on WhatsApp).")
    # A scoped tool takes the group it made: its id is where the operation declares it.
    from nodes.agent.node_op_tools import extract_resource_id_from_output, resource_creators

    [(operation, resource, path)] = resource_creators("automation-whatsapp")
    assert (operation, resource) == ("create_group", "whatsapp_group")
    assert extract_resource_id_from_output(out, path) == GROUP


async def test_adding_and_removing_people_answer_per_person(wahooks):
    wahooks.answers[f"POST /groups/{GROUP}/participants/add"] = (201, {"participants": [
        {"id": "12025550107@c.us", "phone": "12025550107", "lid": None, "status": "added"},
        {"id": "12025550101@c.us", "phone": "12025550101", "lid": None, "status": "already_member"},
        {"id": "12025550104@s.whatsapp.net", "phone": "12025550104", "lid": None, "status": "failed", "code": 408},
        {"id": "12025550102@lid", "phone": None, "lid": "12025550102@lid", "status": "failed", "code": 500,
         "reason": "internal-server-error"}]})
    out = await _tool("add_group_participants", group_id=GROUP,
                      participants=["+12025550107", "12025550101@s.whatsapp.net", "12025550104",
                                    "12025550102@lid"])
    assert wahooks.requests[0][3] == {"participants": ["12025550107", "12025550101@c.us", "12025550104",
                                                       "12025550102@lid"]}
    assert [p["outcome"] for p in out["data"]["people"]] == ["added", "already in the group", "not added",
                                                             "not added"]
    assert out["data"]["summary"] == (
        "Added: +1 202-555-0107. Already in the group: +1 202-555-0101. Not added: +1 202-555-0104 (they left this "
        "group recently, so WhatsApp won't add them back yet: send them the group's invite link); "
        "12025550102@lid (internal-server-error).")

    wahooks.answers[f"POST /groups/{GROUP}/participants/remove"] = (201, {"participants": [
        {"id": "12025550101@c.us", "phone": "12025550101", "lid": None, "status": "removed"},
        {"id": "12025550107@c.us", "phone": "12025550107", "lid": None, "status": "not_member"}]})
    out = await _tool("remove_group_participants", group_id=GROUP, participants=["+12025550101", "+12025550107"])
    assert out["data"]["summary"] == "Removed: +1 202-555-0101. Not in the group: +1 202-555-0107."


async def test_rename_leave_and_the_invite_link(wahooks):
    wahooks.answers[f"PATCH /groups/{GROUP}"] = (200, _group(name="Bakery orders (Nov)"))
    wahooks.answers[f"POST /groups/{GROUP}/leave"] = (201, {"success": True})
    wahooks.answers[f"GET /groups/{GROUP}/invite-link"] = (200, {"link": "https://chat.whatsapp.com/Abc123"})
    wahooks.answers[f"POST /groups/{GROUP}/invite-link/revoke"] = (201, {"link": "https://chat.whatsapp.com/Def456"})

    renamed = await _tool("rename_group", group_id=GROUP, name="Bakery orders (Nov)")
    assert renamed["data"]["summary"] == 'Renamed the group to "Bakery orders (Nov)".'
    assert wahooks.requests[-1][3] == {"name": "Bakery orders (Nov)"}
    link = await _tool("get_group_invite_link", group_id=GROUP)
    assert link["data"]["invite_link"] == "https://chat.whatsapp.com/Abc123"
    revoked = await _tool("revoke_group_invite_link", group_id=GROUP.removesuffix("@g.us"))  # bare digits name it
    assert revoked["data"]["invite_link"] == "https://chat.whatsapp.com/Def456"
    assert "no longer lets anyone join" in revoked["data"]["summary"]
    left = await _tool("leave_group", group_id=GROUP)
    assert left["data"]["left"] is True
    assert [r[:2] for r in wahooks.requests] == [
        ("PATCH", f"/groups/{GROUP}"), ("GET", f"/groups/{GROUP}/invite-link"),
        ("POST", f"/groups/{GROUP}/invite-link/revoke"), ("POST", f"/groups/{GROUP}/leave")]


@pytest.mark.parametrize("status,message,said", [
    (403, "Not an admin of this group", "isn't one of its admins"),
    (404, "Group not found", "WhatsApp deletes a group once its last member leaves"),
    (409, "Connection is not connected", "scanning this credential's QR code"),
    (429, "Too many requests", "wait a minute, then try again"),
    (502, "Bad gateway", "try again shortly"),
    (400, "Group name too long", "WhatsApp refused it (Group name too long)"),
])
async def test_a_refusal_reads_plainly_with_its_status(wahooks, status, message, said):
    wahooks.answers[f"GET /groups/{GROUP}/invite-link"] = (status, {"message": message})
    out = await _tool("get_group_invite_link", group_id=GROUP)
    assert out["status"] == "error" and out["error_code"] == status
    assert said in out["error"] and out["error"].endswith(".")


async def test_an_unreachable_gateway_and_bad_input(wahooks):
    wahooks.down = True
    out = await _tool("get_group", group_id=GROUP)
    assert out["status"] == "error" and "couldn't be reached" in out["error"]
    wahooks.down = False
    # Input that names no group or no person fails the call before anything is sent.
    with pytest.raises(ValueError, match="isn't a WhatsApp group id"):
        await _tool("get_group", group_id="12025550101@c.us")
    with pytest.raises(ValueError, match="international form"):
        await _tool("add_group_participants", group_id=GROUP, participants=["202-555"])
    with pytest.raises(ValueError, match="at most 256"):
        wahooks_groups.participant_ids([f"+1202555{n:04d}" for n in range(257)])
    assert wahooks.requests == [("GET", f"/groups/{GROUP}", {}, None)]


async def test_noclicks_own_line_never_goes_in_a_group(wahooks, monkeypatch):
    monkeypatch.setenv("WHATSAPP_DISPLAY_NUMBER", "+12025550108")
    node = _node(WhatsAppAddGroupParticipantsConfig(group_id=GROUP, participants=["+12025550101", "12025550108"]))
    with pytest.raises(ValueError) as refused:
        await node.execute({})
    assert str(refused.value) == NOCLICK_LINE_IN_GROUP and wahooks.requests == []


def test_the_operations_are_agent_tools_on_a_qr_link_only():
    from nodes.agent.node_op_tools import build_node_op_tools, scopable_fields_for_operation

    operations = ["get_group", "create_group", "rename_group", "add_group_participants",
                  "remove_group_participants", "leave_group", "get_group_invite_link", "revoke_group_invite_link"]
    params, configs = build_node_op_tools("automation-whatsapp", operations, node_id="wa", slug="whatsapp")
    tools = {p["function"]["name"]: p["function"] for p in params}
    assert {f"whatsapp__{op}" for op in operations} <= set(tools)
    assert tools["whatsapp__add_group_participants"]["parameters"]["properties"]["participants"]["type"] == "array"
    assert "who wasn't and why" in tools["whatsapp__create_group"]["description"]
    for op in operations:
        assert WhatsAppNode.operation_credential_types(op) == frozenset({"whatsapp_qr"})
        if op != "create_group":
            assert scopable_fields_for_operation("automation-whatsapp", op) == frozenset({"group_id"})


async def test_the_group_picker_lists_groups_alone(monkeypatch):
    chats = [{"id": "12025550101@c.us", "name": "Asha"}, {"id": GROUP, "name": "Bakery orders"},
             {"id": "120000000000000002@newsletter", "name": "News"}, {"id": "trek", "name": "Trek", "isGroup": True}]
    contacts_read: List[bool] = []

    class Client:
        def __init__(self, api_key):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_chats(self, conn, limit, offset):
            return chats if offset == 0 else []

        def get_contacts(self, conn, limit):
            contacts_read.append(True)
            return [{"jid": "12025550107@c.us", "name": "Kit"}]

    monkeypatch.setenv("WAHOOKS_API_KEY", "wh_test")
    monkeypatch.setattr("wahooks.WAHooks", Client)
    found = await WhatsAppNode.load_field_options("group_id", {"credential_type": "whatsapp_qr",
                                                               "connection_id": LINE})
    assert [(o["value"], o["label"]) for o in found["options"]] == [(GROUP, "Bakery orders"), ("trek", "Trek")]
    assert contacts_read == []


def _people(n: int, start: int = 0) -> List[Dict[str, Any]]:
    return [{"id": f"member-{start + i}@lid", "phone": f"1202555{start + i:04d}", "lid": None,
             "name": f"P{start + i}", "role": "member", "isMe": False} for i in range(n)]


def test_a_groups_turn_names_at_most_thirty_members():
    record = wahooks_groups.turn_record(_group(*_people(33), ASHA), sender=ASHA["id"])
    assert len(record["members"]) == 30 and record["more"] == 4 and record["members"][0]["name"] == "Asha"
    note = wahooks_groups.members_note(record)
    assert note.startswith(" It has 34 members besides you: Asha (+1 202-555-0101, admin), P0 (+1 202-555-0000)")
    assert ", and 4 more." in note and "The sender is one of its admins. You're one of its admins." in note

    alone = wahooks_groups.turn_record(_group(me={**ME, "role": "member"}))
    assert wahooks_groups.members_note(alone) == (
        " No one else is in it. You aren't one of its admins, so you can't add or remove people or share its invite "
        "link.")
    # A member named only by their number reads as the number; one with none shown, as hidden.
    unnamed = wahooks_groups.turn_record(_group({**ASHA, "name": "+1 202 555 0101", "role": "member"}, KIT))
    assert wahooks_groups.members_note(unnamed).startswith(
        " It has 2 members besides you: +1 202-555-0101, someone with a hidden number.")


def test_a_sender_is_matched_by_their_id_or_their_lid():
    ravi = {"id": "12025550101@c.us", "phone": "12025550101", "lid": "12025550103@lid", "name": "Ravi",
            "role": "admin", "isMe": False}
    for sender in ("12025550103@lid", "12025550101@c.us", "12025550101@s.whatsapp.net"):
        assert wahooks_groups.turn_record(_group(ravi), sender=sender)["sender_admin"] is True
    assert wahooks_groups.turn_record(_group(ravi), sender="12025550107@c.us")["sender_admin"] is None
