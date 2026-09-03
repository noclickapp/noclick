"""Hand-authored worlds for rehearsing a template's agent.

Kept here rather than in template storage while there is one of them. Moving
these to a `rehearsal` block on the template row is a small change and the
obvious next step once a second template needs one — the shape below is already
what that column would hold.

Authoring rules, restated because they are easy to get wrong:

* ``scenario`` describes the SITUATION, never the desired outcome. "The agent
  should reply warmly and offer a call" produces a rehearsal that flatters the
  agent instead of showing what it actually does.
* ``trigger_payload`` is the exact provider shape. It is hand-authored and never
  generated: each node class translates it through ``resolve_agent_event`` to
  build the agent's turn, so an almost-right payload breaks the run for reasons
  nothing on screen explains.
"""

from __future__ import annotations

from typing import Dict, Optional

from nodes.agent.rehearsal import RehearsalScenario

# Every identity, organisation, address, URL, identifier, and event below is
# hand-authored synthetic data. Reserved ``.example`` domains and the NANP
# 555-0100–0199 fiction range make that provenance visible in the values too.

# The inbound lead the sales agent rehearses against. Deliberately a lead worth
# reacting to but not a caricature: a realistic question, a fictional company, and enough
# detail that a good briefing and a lazy one look different.
SALES_INBOUND_LEAD = RehearsalScenario(
    scenario=(
        "Casey Example, Operations Manager at Example Manufacturing (a "
        "fictional forty-person manufacturer), has emailed the sales inbox. "
        "She wants purchase-order approval requests routed into Slack "
        "automatically and asks whether that is possible and what it costs. "
        "She has not spoken to anyone at the company before. Her company has a "
        "fictional product page returned by the rehearsal's mock tools. The sales Slack "
        "workspace has the usual channels a startup has, including one the team "
        "uses for inbound leads."
    ),
    # Matched to the node the onboarding template wires as its trigger; the
    # runner resolves the real node id from the saved graph by type, so this is
    # a placeholder and never used for routing.
    trigger_node_id="",
    trigger_payload={
        "id": "example-message-qualified",
        "thread_id": "example-thread-qualified",
        "from": "Casey Example <casey@example-manufacturing.example>",
        "to": "sales@example.com",
        "subject": "Routing purchase-order approvals into Slack",
        "snippet": (
            "Hi — we're evaluating options for routing purchase-order approval "
            "requests into Slack automatically."
        ),
        "body": (
            "Hi there,\n\n"
            "I'm Casey, Operations Manager at Example Manufacturing. My team "
            "reviews purchase-order requests in a shared inbox.\n\n"
            "I'd like new requests to land in Slack with an approval link. Is "
            "that something you support, and roughly what does it cost for a "
            "team of about twelve?\n\n"
            "Thanks,\nCasey"
        ),
        "internal_date": "1700000000000",
        "label_ids": ["INBOX", "UNREAD"],
    },
)

#: Slug -> scenario, derived from STAGED_SITUATIONS below. The slug is what the
#: client asks for, so it is part of the contract and should not be renamed
#: casually.
SCENARIOS: Dict[str, RehearsalScenario] = {}

#: Which node type each scenario's payload is shaped for. The runner uses this
#: to find the real trigger node in the saved graph, so a template can be
#: rebuilt or re-imported without the scenario going stale on a changed node id.
SCENARIO_TRIGGER_NODE_TYPES: Dict[str, str] = {}

# ---------------------------------------------------------------------------
# Additional staged situations. One trigger is not one situation: a qualified
# lead, a one-line inquiry and a newsletter should produce visibly different
# behaviour — including the behaviour of doing nothing at all.
# ---------------------------------------------------------------------------

def _gmail_payload(**over: object) -> Dict[str, object]:
    """The gmail trigger's payload shape, varied per situation. One template so
    a field rename in the trigger breaks every scenario loudly at once instead
    of one of them quietly."""
    base: Dict[str, object] = {
        "id": "example-message-base",
        "thread_id": "example-thread-base",
        "from": "someone@example.com",
        "to": "sales@example.com",
        "subject": "",
        "snippet": "",
        "body": "",
        "internal_date": "1700000000000",
        "label_ids": ["INBOX", "UNREAD"],
    }
    base.update(over)
    return base


THIN_INQUIRY = RehearsalScenario(
    scenario=(
        "Sam Example has emailed the sales inbox one line: does the product "
        "work with Slack. No company, no context, no use case. Nothing else is "
        "known about Sam. The Slack workspace has the usual startup channels, "
        "including one for inbound leads."
    ),
    trigger_node_id="",
    trigger_payload=_gmail_payload(
        id="example-message-thin",
        thread_id="example-thread-thin",
        **{"from": "Sam Example <sam@brightops.example>"},
        subject="Quick question",
        snippet="Hi — does your product work with Slack? Thanks, Sam",
        body="Hi — does your product work with Slack?\n\nThanks,\nSam",
    ),
)

NEWSLETTER = RehearsalScenario(
    scenario=(
        "A marketing newsletter has landed in the sales inbox: growth-hack "
        "content from a fictional company called Example Bulletin, sent to a list. It is not "
        "from a person and asks for nothing. The Slack workspace has the usual "
        "startup channels, including one for inbound leads."
    ),
    trigger_node_id="",
    trigger_payload=_gmail_payload(
        id="example-message-newsletter",
        thread_id="example-thread-newsletter",
        **{"from": "Example Bulletin <newsletter@bulletin.example>"},
        subject="🚀 5 growth hacks your ops team needs this quarter",
        snippet="Unlock the secrets top logistics teams use to 10x their pipeline!",
        body=(
            "Unlock the secrets top logistics teams use to 10x their pipeline! "
            "This week: cold outreach templates, the AI tools everyone is "
            "talking about, and more…\n\nUnsubscribe | Preferences"
        ),
        label_ids=["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"],
    ),
)


# ---------------------------------------------------------------------------
# What the client is offered, grouped by the trigger node type the payload is
# shaped for. `lead` is display-only — the staged message as the test screen
# renders it — and must agree with the payload, because showing one email and
# injecting another would make the whole screen a lie.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Channel triggers. Each payload is shaped for what that node's
# resolve_agent_event actually READS — slack wants data.event.{text,channel,ts},
# whatsapp wants event/payload.{from,body}, telegram wants message.{text,chat} —
# because an almost-right payload falls through to the raw-JSON default and the
# agent gets a JSON dump instead of a message.
# ---------------------------------------------------------------------------

SLACK_TEAMMATE_ASKS = RehearsalScenario(
    scenario=(
        "Jordan Example, a sales teammate, has posted in the #inbound-leads Slack "
        "channel asking whether anyone has handled the Example Manufacturing lead — Casey "
        "Example emailed twice about routing purchase-order approvals into Slack and has "
        "not been answered. The shared inbox contains her two emails. The "
        "workspace has the usual startup channels."
    ),
    trigger_node_id="",
    trigger_payload={
        "data": {
            "event": {
                "type": "message",
                "text": "@lead-agent anyone looked at the Example Manufacturing note yet? Casey pinged again this morning about the approval workflow.",
                "user": "U0EXAMPLE",
                "channel": "C0EXAMPLE1",
                "ts": "1700000000.000001",
                "channel_type": "channel",
            }
        }
    },
)

WHATSAPP_DIRECT_LEAD = RehearsalScenario(
    scenario=(
        "Casey Example, Operations Manager at Example Manufacturing, has messaged "
        "the business WhatsApp number directly: she found the company through "
        "an ops community, wants purchase-order approvals routed into Slack for a "
        "team of about twelve, and asks about cost. She has never been spoken "
        "to before. The sales Slack workspace has a channel for inbound leads."
    ),
    trigger_node_id="",
    trigger_payload={
        "event": "message",
        "payload": {
            "id": "wamid.synthetic-qualified-001",
            "from": "12025550107@c.us",
            "body": "Hi — found you through an ops group. Can you route purchase-order approvals from email into Slack? Team of about 12. What does it cost?",
            "hasMedia": False,
            "_data": {"key": {"remoteJid": "12025550107@c.us"}},
        },
    },
)

WHATSAPP_OPT_OUT = RehearsalScenario(
    scenario=(
        "Morgan Example has replied to the business WhatsApp number with a clear "
        "opt-out: stop messaging me, not interested. Nothing else is known "
        "about him. The worst possible move is another message."
    ),
    trigger_node_id="",
    trigger_payload={
        "event": "message",
        "payload": {
            "id": "wamid.synthetic-opt-out-001",
            "from": "12025550108@c.us",
            "body": "Please stop messaging me. Not interested.",
            "hasMedia": False,
            "_data": {"key": {"remoteJid": "12025550108@c.us"}},
        },
    },
)

TELEGRAM_DIRECT_LEAD = RehearsalScenario(
    scenario=(
        "Casey Example, Operations Manager at Example Manufacturing, has messaged "
        "the company's Telegram bot directly: she wants purchase-order approvals "
        "routed into Slack for a team of about twelve and asks about cost. She "
        "has never been spoken to before. The sales Slack workspace has a "
        "channel for inbound leads."
    ),
    trigger_node_id="",
    trigger_payload={
        "message": {
            "message_id": 4021,
            "from": {"id": 100000001, "is_bot": False, "first_name": "Casey", "username": "caseyexample"},
            "chat": {"id": 100000001, "type": "private", "first_name": "Casey", "username": "caseyexample"},
            "date": 1700000000,
            "text": "Hi — can you route purchase-order approvals from email into Slack? Team of about 12. What does it cost?",
        }
    },
)


# Shaped like the Gateway envelope the Discord listener forwards
# (utils/discord_gateway_bridge.build_gateway_envelope): the node's
# resolve_trigger_payload reads `d` as the message and the names off the
# envelope; the bot's own mention is stripped from the agent's turn.
DISCORD_CHANNEL_QUESTION = RehearsalScenario(
    scenario=(
        "Casey Example, a member of the company's Discord server, has posted in "
        "the #support channel asking whether purchase-order approvals can be "
        "routed from email into Slack for a team of about twelve, and what it "
        "costs. She mentioned the bot and has not been answered. The server has "
        "the usual community channels."
    ),
    trigger_node_id="",
    trigger_payload={
        "source": "gateway",
        "t": "MESSAGE_CREATE",
        "d": {
            "id": "100000000000000401",
            "type": 0,
            "content": "Hey <@100000000000000001> — can you route purchase-order approvals from email into Slack? Team of about 12. What does it cost?",
            "channel_id": "100000000000000093",
            "guild_id": "100000000000000090",
            "timestamp": "2024-01-01T09:14:00+00:00",
            "author": {"id": "100000000000000210", "username": "caseyexample", "global_name": "Casey Example", "bot": False},
            "member": {"nick": None},
            "mentions": [{"id": "100000000000000001", "username": "assistant", "global_name": "Assistant", "bot": True}],
            "attachments": [],
            "embeds": [],
        },
        "bot_user_id": "100000000000000001",
        "application_id": "100000000000000001",
        "guild_name": "Example Community",
        "channel_name": "support",
        "received_at": 1700000000.0,
    },
)


STAGED_SITUATIONS: Dict[str, list] = {
    "automation-gmail": [
        {
            "key": "sales-inbound-lead",
            "name": "Qualified lead",
            "scenario": SALES_INBOUND_LEAD,
            "lead": {
                "title": "Routing purchase-order approvals into Slack",
                "meta": "Casey Example <casey@example-manufacturing.example>",
                "author": "Casey Example",
                "handle": "casey@example-manufacturing.example",
                "time": "09:32",
                "body": (
                    "I'm Casey, Operations Manager at Example Manufacturing. My "
                    "team reviews purchase-order requests in a shared inbox. I'd "
                    "like new requests to land in Slack with an approval link. Is "
                    "that something you support, and roughly what does it cost "
                    "for a team of about twelve?"
                ),
            },
        },
        {
            "key": "thin-inquiry",
            "name": "Thin inquiry",
            "scenario": THIN_INQUIRY,
            "lead": {
                "title": "Quick question",
                "meta": "Sam Example <sam@brightops.example>",
                "author": "Sam Example",
                "handle": "sam@brightops.example",
                "time": "11:05",
                "body": "Hi — does your product work with Slack? Thanks, Sam",
            },
        },
        {
            "key": "newsletter",
            "name": "Newsletter",
            "scenario": NEWSLETTER,
            "lead": {
                "title": "🚀 5 growth hacks your ops team needs this quarter",
                "meta": "Example Bulletin <newsletter@bulletin.example>",
                "author": "Example Bulletin",
                "handle": "newsletter@bulletin.example",
                "time": "08:00",
                "body": (
                    "Unlock the secrets top logistics teams use to 10x their "
                    "pipeline! This week: cold outreach templates, the AI tools "
                    "everyone is talking about, and more…"
                ),
            },
        },
    ],
    "automation-slack": [
        {
            "key": "slack-teammate-asks",
            "name": "Teammate asks",
            "scenario": SLACK_TEAMMATE_ASKS,
            "lead": {
                "title": "#inbound-leads",
                "meta": "Jordan Example · 09:14",
                "author": "Jordan Example",
                "time": "09:14",
                "body": "@lead-agent anyone looked at the Example Manufacturing note yet? Casey pinged again this morning about the approval workflow.",
            },
        },
    ],
    "automation-whatsapp": [
        {
            "key": "whatsapp-direct-lead",
            "name": "Direct lead",
            "scenario": WHATSAPP_DIRECT_LEAD,
            "lead": {
                "title": "Casey Example",
                "meta": "+1 (415) 555-0184 · 09:41",
                "author": "Casey Example",
                "handle": "+1 (415) 555-0184",
                "time": "09:41",
                "body": "Hi — found you through an ops group. Can you route purchase-order approvals from email into Slack? Team of about 12. What does it cost?",
            },
        },
        {
            "key": "whatsapp-opt-out",
            "name": "Opt-out",
            "scenario": WHATSAPP_OPT_OUT,
            "lead": {
                "title": "Morgan Example",
                "meta": "+1 (415) 555-0139 · 08:57",
                "author": "Morgan Example",
                "handle": "+1 (415) 555-0139",
                "time": "08:57",
                "body": "Please stop messaging me. Not interested.",
            },
        },
    ],
    "automation-telegram": [
        {
            "key": "telegram-direct-lead",
            "name": "Direct lead",
            "scenario": TELEGRAM_DIRECT_LEAD,
            "lead": {
                "title": "Casey Example",
                "meta": "@caseyexample · 09:41",
                "author": "Casey Example",
                "handle": "@caseyexample",
                "time": "09:41",
                "body": "Hi — can you route purchase-order approvals from email into Slack? Team of about 12. What does it cost?",
            },
        },
    ],
    "automation-discord": [
        {
            "key": "discord-channel-question",
            "name": "Channel question",
            "scenario": DISCORD_CHANNEL_QUESTION,
            "lead": {
                "title": "#support",
                "meta": "Casey Example · 09:14",
                "author": "Casey Example",
                "handle": "@caseyexample",
                "time": "09:14",
                "body": "@Assistant — can you route purchase-order approvals from email into Slack? Team of about 12. What does it cost?",
            },
        },
    ],
}



# ---------------------------------------------------------------------------
# The generic fallback: any trigger the registry has not hand-authored gets a
# staged sample event. The base resolve_agent_event delivers the payload as raw
# JSON in the agent's turn, so this works for EVERY trigger type by
# construction — less pretty than an authored situation, but "your trigger is
# rehearsable today" beats "wait for us to write your scenario".
# ---------------------------------------------------------------------------

GENERIC_KEY_PREFIX = "generic:"


def make_generic_scenario(node_type: str) -> RehearsalScenario:
    return RehearsalScenario(
        scenario=(
            f"A staged sample event has arrived at the workflow's {node_type} "
            "trigger. Its exact provider shape is not modelled, so the agent "
            "sees the raw event JSON. Behave exactly as on a real event."
        ),
        trigger_node_id="",
        trigger_payload={
            "staged": True,
            "event": "sample",
            "note": (
                "This is a staged sample event for a test run. Nothing outward "
                "will be sent."
            ),
            "received_at": "2024-01-01T00:00:00Z",
        },
    )


def _generic_lead(node_type: str) -> Dict[str, str]:
    return {
        "title": "Sample event",
        "meta": node_type,
        "body": (
            "A staged sample event arrives at this trigger. Its provider shape "
            "is not modelled yet, so the agent sees the raw event JSON — edit "
            "this message to stage the exact event you want it to handle."
        ),
    }


# What the staged card lets the builder rewrite — lead terms, the fields the
# card SHOWS. Each provider maps them onto its own payload shape below, so an
# edited event still survives the node's resolve_agent_event reader.
LEAD_PATCH_FIELDS = frozenset({"title", "body", "author", "handle"})


def apply_lead_patch(node_type: str, scenario, patch: Dict[str, str]):
    """Rebuild a staged scenario with the builder's edits, payload included.

    Editing must be REAL: the card's pencil earlier patched only the display
    while the run injected the authored payload — a control that lies. Unknown
    fields and uneditable trigger types are refused loudly rather than applied
    partially. The authored scenario object is never mutated (they are module
    singletons); the world-briefing gains a note carrying the edited content so
    the mock model's world stays consistent with what the agent actually read.
    """
    import copy
    from dataclasses import replace

    unknown = set(patch) - LEAD_PATCH_FIELDS
    if unknown:
        raise ValueError(f"unknown staged-message fields: {sorted(unknown)}")
    clean = {
        k: v.strip() for k, v in patch.items() if isinstance(v, str) and v.strip()
    }
    if not clean:
        return scenario
    for k, v in clean.items():
        if len(v) > 8000:
            raise ValueError(f"staged-message field '{k}' is too long")

    payload = copy.deepcopy(scenario.trigger_payload)
    title, body = clean.get("title"), clean.get("body")
    author, handle = clean.get("author"), clean.get("handle")

    if node_type == "automation-gmail":
        if title:
            payload["subject"] = title
        if body:
            payload["body"] = body
            payload["snippet"] = body.split("\n", 1)[0][:180]
        if author or handle:
            cur = str(payload.get("from") or "")
            cur_name = cur.split("<")[0].strip() or "Someone"
            cur_email = cur[cur.find("<") + 1 : cur.find(">")] if "<" in cur else cur
            payload["from"] = f"{author or cur_name} <{handle or cur_email}>"
    elif node_type == "automation-slack":
        # The Slack event carries a user ID, not a display name — author/handle
        # edits change only the card's rendering, and that is all they can mean.
        if body:
            payload["data"]["event"]["text"] = body
    elif node_type == "automation-discord":
        message = payload["d"]
        if body:
            message["content"] = body
        if author:
            message["author"]["global_name"] = author
        if handle:
            message["author"]["username"] = handle.lstrip("@")
    elif node_type == "automation-whatsapp":
        if body:
            payload["payload"]["body"] = body
    elif node_type == "automation-telegram":
        msg = payload["message"]
        if body:
            msg["text"] = body
        if author:
            msg["from"]["first_name"] = author
            msg["chat"]["first_name"] = author
        if handle:
            username = handle.lstrip("@")
            msg["from"]["username"] = username
            msg["chat"]["username"] = username
    elif payload.get("staged") is True:
        # A generic sample is OURS — flat JSON with no provider reader to
        # satisfy — so the edit simply becomes the event: every lead field
        # lands as a payload key the base resolve_agent_event delivers
        # verbatim, and nothing the builder typed silently vanishes.
        for key, value in (
            ("subject", title),
            ("content", body),
            ("author", author),
            ("handle", handle),
        ):
            if value:
                payload[key] = value
    else:
        # A provider-shaped payload with no mapping here: an edit that
        # silently failed to reach the payload is the lie this exists to end.
        raise ValueError(f"staged events for {node_type} cannot be edited yet")

    edited = []
    if title:
        edited.append(f"subject: {title!r}")
    if body:
        edited.append(f"message: {body!r}")
    scenario_text = scenario.scenario
    if edited:
        scenario_text = (
            f"{scenario_text}\n\nThe builder edited the staged message before "
            f"running — the event actually delivered says {'; '.join(edited)}."
        )
    return replace(scenario, scenario=scenario_text, trigger_payload=payload)


def can_stage_trigger(node: dict, workflow_nodes: list, workflow_edges: Optional[list]) -> bool:
    """Whether a staged event landing on this node tells the promised story:
    event in, agent turn out.

    Two disqualifiers, both found on real graphs. A PROVIDER-WIRED node is the
    agent's tool, not its trigger — the runner drops a trigger payload landing
    on one (provider mode wins), so staging an event there rehearses nothing
    (the 2026-08-10 Telegram case: wired bottom-handle, offered as a trigger,
    silently eventless). And a node from which no agent is forward-reachable
    runs a subgraph with no agent in it — the test "completes" having shown
    nothing. Presence-by-type answers neither; only the wiring does.
    """
    from nodes.agent.node_op_tools import is_node_op_provider

    node_id = node.get("id")
    if is_node_op_provider(node_id, node.get("type"), workflow_nodes, workflow_edges):
        return False
    agent_ids = {n.get("id") for n in (workflow_nodes or []) if n.get("type") == "agent"}
    if not agent_ids:
        return False
    successors: Dict[str, list] = {}
    for e in workflow_edges or []:
        s, t = e.get("source"), e.get("target")
        if s and t:
            successors.setdefault(s, []).append(t)
    seen = {node_id}
    queue = list(successors.get(node_id, []))
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in agent_ids:
            return True
        queue.extend(successors.get(cur, []))
    return False


def staged_for_graph(workflow_nodes: list, workflow_edges: Optional[list] = None) -> list:
    """The situations this workflow can actually rehearse.

    A situation is offered only when the graph contains a node of the trigger
    type its payload is shaped for, WIRED so the event would reach an agent
    (``can_stage_trigger``) — offering a Gmail situation to a workflow with no
    stageable Gmail trigger would fail at run time with a message the user has
    no way to act on from the picker.
    """
    from nodes.agent.node_op_tools import is_trigger_operation

    stageable = [
        n for n in (workflow_nodes or [])
        if can_stage_trigger(n, workflow_nodes, workflow_edges)
    ]
    stageable_types = {n.get("type") for n in stageable}
    # The selected trigger operation per type — the FE frames respond to it
    # (a PR trigger renders a PR card, invoice.paid an invoice).
    op_by_type: Dict[str, str] = {}
    for n in stageable:
        node_type = n.get("type") or ""
        op = (n.get("config") or {}).get("operation")
        if node_type not in op_by_type and isinstance(op, str) and op:
            op_by_type[node_type] = op
    out = []
    for node_type, situations in STAGED_SITUATIONS.items():
        if node_type not in stageable_types:
            continue
        out.append({
            "node_type": node_type,
            **({"operation": op_by_type[node_type]} if node_type in op_by_type else {}),
            "situations": [
                {"key": s["key"], "name": s["name"], "lead": s["lead"]}
                for s in situations
            ],
        })

    # Everything else that is recognisably a trigger gets the generic sample:
    # dedicated trigger nodes by type prefix, and provider nodes whose SELECTED
    # operation is a trigger op. A provider node with no operation chosen is
    # not offered — it could not fire for real either.
    covered = set(STAGED_SITUATIONS)
    seen_generic = set()
    for n in stageable:
        node_type = n.get("type") or ""
        if node_type in covered or node_type in seen_generic:
            continue
        # Fetched-graph shape: the operation lives in the flat config blob.
        # Reading data.operation — a shape live graphs never have — kept every
        # provider trigger out of the offer (the 2026-08-10 cal.com report).
        op = (n.get("config") or {}).get("operation")
        is_trigger = node_type.startswith("trigger-") or (
            op and is_trigger_operation(node_type, op)
        )
        if not is_trigger:
            continue
        seen_generic.add(node_type)
        out.append({
            "node_type": node_type,
            **({"operation": op} if op else {}),
            "situations": [{
                "key": f"{GENERIC_KEY_PREFIX}{node_type}",
                "name": "Sample event",
                "lead": _generic_lead(node_type),
            }],
        })
    return out


def base_scenario_key_for_type(node_type: str) -> str:
    """The scenario key a builder-authored test run rides on: the first
    authored situation for the type, else the generic sample. An authored
    run's WHOLE lead travels as the lead patch, so the base only supplies
    the payload shape — content never leaks through."""
    situations = STAGED_SITUATIONS.get(node_type)
    if situations:
        return situations[0]["key"]
    return f"{GENERIC_KEY_PREFIX}{node_type}"


# Derive the flat runner contract from the grouped registry so the two can
# never disagree about which scenarios exist.
for _node_type, _situations in STAGED_SITUATIONS.items():
    for _s in _situations:
        SCENARIOS[_s["key"]] = _s["scenario"]
        SCENARIO_TRIGGER_NODE_TYPES[_s["key"]] = _node_type
