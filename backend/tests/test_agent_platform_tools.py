"""Platform tools (submit_feedback / prompt_builder) — injection gating, mode
derivation from the conversation key, and the three prompt_builder behaviors
(interactive approval card, shared refusal, background headless spawn).
"""
from unittest.mock import AsyncMock, MagicMock, patch

from nodes.agent.platform_tools import (
    PLATFORM_TOOL_TYPES,
    PROMPT_BUILDER_TOOL,
    SUBMIT_FEEDBACK_TOOL,
    build_platform_tools,
    prompt_builder_mode,
    prompt_builder_impl,
    submit_feedback_impl,
)


def _tool_names(pairs):
    return [param["function"]["name"] for param, _cfg in pairs]


class TestBuildPlatformTools:
    def test_prompt_builder_enabled_by_default_flag(self):
        from nodes.agent.platform_tools import (
            BUILDER_RESPOND_TOOL,
            DESCRIBE_WORKFLOW_TOOL,
        )

        assert _tool_names(build_platform_tools(True)) == [
            SUBMIT_FEEDBACK_TOOL, PROMPT_BUILDER_TOOL, BUILDER_RESPOND_TOOL,
            DESCRIBE_WORKFLOW_TOOL,
        ]

    def test_prompt_builder_disabled(self):
        assert _tool_names(build_platform_tools(False)) == [SUBMIT_FEEDBACK_TOOL]

    def test_email_updates_opt_in(self):
        # email_user is opt-in and independent of the builder flag.
        from nodes.agent.platform_tools import EMAIL_USER_TOOL

        assert EMAIL_USER_TOOL not in _tool_names(build_platform_tools(True))
        assert _tool_names(build_platform_tools(False, True)) == [
            SUBMIT_FEEDBACK_TOOL, EMAIL_USER_TOOL,
        ]
        assert _tool_names(build_platform_tools(True, True))[-1] == EMAIL_USER_TOOL

    def test_community_build_withholds_email_tool_and_steering(self, monkeypatch):
        from nodes.agent.platform_tools import EMAIL_USER_TOOL, platform_tools_note

        monkeypatch.setenv("NOCLICK_LOCAL", "1")
        monkeypatch.delenv("INBOUND_EMAIL_DOMAIN", raising=False)
        assert EMAIL_USER_TOOL not in _tool_names(build_platform_tools(True, True))
        assert "email_user" not in platform_tools_note(True, True)

    def test_community_email_tool_requires_operator_domain(self, monkeypatch):
        from nodes.agent.platform_tools import EMAIL_USER_TOOL

        monkeypatch.setenv("NOCLICK_LOCAL", "1")
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mail.automation.example.test")
        assert EMAIL_USER_TOOL in _tool_names(build_platform_tools(True, True))

    def test_iteration_fanout_withholds_ambient_email(self):
        from nodes.agent.platform_tools import EMAIL_USER_TOOL

        names = _tool_names(build_platform_tools(True, True, in_iteration=True))
        assert EMAIL_USER_TOOL not in names
        assert SUBMIT_FEEDBACK_TOOL in names
        assert PROMPT_BUILDER_TOOL in names

    def test_iteration_context_detection(self):
        from nodes.agent.platform_tools import inputs_are_iteration_fanout

        assert inputs_are_iteration_fanout({
            "loop_1": {"isIterationNode": True, "item": {"coin": "BTC"}},
        })
        assert not inputs_are_iteration_fanout({
            "source": {"isIterationNode": False}, "other": "value",
        })

    def test_tool_configs_carry_platform_types(self):
        for _param, cfg in build_platform_tools(True, True):
            assert cfg["tool_type"] in PLATFORM_TOOL_TYPES

    def test_tool_configs_carry_shadow_advertisement(self):
        # The tool bundle entry builder reads _description/_parameters off the
        # CONFIG (node_op convention). Without them the CLI harnesses advertised
        # the platform tools with no description and no arguments — unusable
        # (2026-07-18: agent enumerated its tools and omitted both).
        for param, cfg in build_platform_tools(True, True):
            fn = param["function"]
            assert cfg["_description"] == fn["description"]
            assert cfg["_description"], "description must be non-empty"
            assert cfg["_parameters"] == fn["parameters"]
            assert cfg["_parameters"]["properties"], "schema must declare args"
            # builder_respond / describe_workflow legitimately require nothing;
            # the others must declare their required arg.
            if fn["name"] not in ("builder_respond", "describe_workflow"):
                assert cfg["_parameters"]["required"], "schema must declare its required arg"

    def test_submit_feedback_requires_a_stable_issue_key(self):
        submit_param = build_platform_tools(False)[0][0]["function"]

        assert submit_param["parameters"]["required"] == ["feedback", "issue_key"]
        description = submit_param["description"]
        assert "progress narration" in description
        assert "missing user input" in description
        assert "Reuse the exact same issue_key" in description


class TestPlatformToolsNote:
    def test_submit_feedback_steering_survives_prompt_builder_disable(self):
        # submit_feedback is ALWAYS injected, so its report-platform-bugs
        # steering must ride every turn even when workflow edits are off —
        # the single-flag gate used to strip both together.
        from nodes.agent.platform_tools import platform_tools_note

        with_pb = platform_tools_note(True)
        without_pb = platform_tools_note(False)
        assert "prompt_builder" in with_pb and "submit_feedback" in with_pb
        assert "submit_feedback" in without_pb
        assert "prompt_builder" not in without_pb

    def test_email_steering_rides_only_when_enabled(self):
        from nodes.agent.platform_tools import platform_tools_note

        assert "email_user" in platform_tools_note(True, True)
        assert "email_user" not in platform_tools_note(True, False)
        # And email steering survives the builder flag being off.
        note = platform_tools_note(False, True)
        assert "email_user" in note and "submit_feedback" in note
        assert "email_user" not in platform_tools_note(True, True, in_iteration=True)

    def test_feedback_note_excludes_non_platform_failures(self):
        from nodes.agent.platform_tools import platform_tools_note

        note = platform_tools_note(False)
        assert "Never use it for progress updates" in note
        assert "missing user input/data/credentials" in note


class TestAnchoredBuilderPrompt:
    def test_names_the_requesting_agent(self):
        from nodes.agent.platform_tools import anchored_builder_prompt

        out = anchored_builder_prompt("add telegram support", "agent_a")
        assert out.startswith("add telegram support")
        assert "'agent_a'" in out
        assert "other agent nodes" in out

    def test_no_node_id_passes_through(self):
        from nodes.agent.platform_tools import anchored_builder_prompt

        assert anchored_builder_prompt("do x", None) == "do x"


class TestPromptBuilderMode:
    def test_interface_chat_is_interactive(self):
        # Default thread = the bare FE constant (TWO trailing underscores);
        # later threads append _<suffix>. Both must be interactive.
        assert prompt_builder_mode("__interface_chat__") == "interactive"
        assert prompt_builder_mode("__interface_chat___abc123") == "interactive"

    def test_share_link_is_shared(self):
        assert prompt_builder_mode("share:lnk:visitor:chat") == "shared"

    def test_everything_else_is_background(self):
        for ck in (None, "", "my-cron-key", "telegram:12345"):
            assert prompt_builder_mode(ck) == "background"


class TestSubmitFeedback:
    async def test_records_agent_bug_feedback(self):
        pool = MagicMock()
        with patch("utils.feedback.record_feedback", new=AsyncMock()) as rec:
            result = await submit_feedback_impl(
                pool=pool, user_id="u1", workflow_id="w1", node_id="n1",
                execution_id="e1", conversation_id="c1", model="gpt-5.4-mini",
                feedback="tool X 500s", issue_key="tool_x_http_500",
            )
        assert result["success"] is True
        kwargs = rec.call_args.kwargs
        assert rec.call_args.args == (pool,)
        assert kwargs["user_id"] == "u1"
        assert kwargs["feedback_type"] == "agent_bug"
        assert kwargs["message"] == "tool X 500s"
        assert kwargs["metadata"]["workflow_id"] == "w1"
        assert kwargs["metadata"]["node_id"] == "n1"
        assert kwargs["metadata"]["execution_id"] == "e1"
        assert kwargs["metadata"]["model"] == "gpt-5.4-mini"
        assert kwargs["metadata"]["agent_issue_key"] == "tool_x_http_500"
        assert kwargs["dedupe_key"] == "w1:n1:tool_x_http_500"

    async def test_recent_duplicate_is_suppressed(self):
        with patch(
            "utils.feedback.record_feedback", new=AsyncMock(return_value=False),
        ):
            result = await submit_feedback_impl(
                pool=MagicMock(), user_id="u1", workflow_id="w1", node_id="n1",
                execution_id="e2", conversation_id="c1", model=None,
                feedback="same failure", issue_key="tool_x_http_500",
            )
        assert result["success"] is True
        assert result["status"] == "duplicate_suppressed"
        assert "Do not call submit_feedback" in result["message"]

    async def test_legacy_schema_gets_stable_fallback_key(self):
        with patch(
            "utils.feedback.record_feedback", new=AsyncMock(return_value=True),
        ) as rec:
            await submit_feedback_impl(
                pool=MagicMock(), user_id="u1", workflow_id="w1", node_id="n1",
                execution_id="e1", conversation_id="c1", model=None,
                feedback="Tool X returned the wrong result",
            )
        issue_key = rec.call_args.kwargs["metadata"]["agent_issue_key"]
        assert issue_key.startswith("legacy_")
        assert rec.call_args.kwargs["dedupe_key"] == f"w1:n1:{issue_key}"

    async def test_empty_feedback_rejected(self):
        with patch("utils.feedback.record_feedback", new=AsyncMock()) as rec:
            result = await submit_feedback_impl(
                pool=MagicMock(), user_id="u1", workflow_id="w1", node_id="n1",
                conversation_id="c1", model=None, feedback="   ",
            )
        assert result["success"] is False
        rec.assert_not_called()

    async def test_missing_user_rejected(self):
        with patch("utils.feedback.record_feedback", new=AsyncMock()) as rec:
            result = await submit_feedback_impl(
                pool=MagicMock(), user_id=None, workflow_id="w1", node_id="n1",
                conversation_id="c1", model=None, feedback="bug",
            )
        assert result["success"] is False
        rec.assert_not_called()


class TestPromptBuilder:
    async def test_shared_mode_refused(self):
        result = await prompt_builder_impl(
            pool=MagicMock(),
            user_id="owner", workflow_id="w1", node_id="n1",
            conversation_id="c1", conversation_key="share:lnk:v:c",
            prompt="add a slack node",
        )
        assert result["success"] is False
        assert "shared" in result["error"]

    async def test_empty_prompt_rejected(self):
        result = await prompt_builder_impl(
            pool=MagicMock(), user_id="u1", workflow_id="w1", node_id="n1",
            conversation_id="c1", conversation_key=None, prompt="  ",
        )
        assert result["success"] is False

    async def test_missing_workflow_context_rejected(self):
        result = await prompt_builder_impl(
            pool=MagicMock(), user_id="u1", workflow_id=None, node_id="n1",
            conversation_id="c1", conversation_key=None, prompt="do it",
        )
        assert result["success"] is False

    async def test_interactive_emits_and_persists_approval_card(self):
        # The card must ALSO land in conversations.events: the chat's
        # reconcile poll adopts the persisted transcript wholesale on turn
        # end, so a live-only card vanished as soon as the turn finished.
        repo = MagicMock()
        repo.append_chat_event = AsyncMock()
        with patch("utils.event_relay.broadcast_to_user_safe", new=AsyncMock()) as bc, \
             patch("repositories.conversation.ConversationRepo", return_value=repo):
            result = await prompt_builder_impl(
                pool=MagicMock(),
                user_id="u1", workflow_id="w1", node_id="n1",
                conversation_id="c1",
                conversation_key="__interface_chat___k",
                prompt="add a slack node",
            )
        assert result["success"] is True
        assert result["status"] == "approval_requested"
        (user_id, event), _ = bc.call_args
        assert user_id == "u1"
        assert event.conversation_id == "c1"
        proposal = event.builder_prompt
        assert proposal is not None
        assert proposal.prompt == "add a slack node"
        assert proposal.node_id == "n1"
        assert proposal.proposal_id
        # The approve submits the ANCHORED variant so a multi-agent workflow
        # can't misroute the edit; the card displays the clean prompt.
        assert proposal.anchored_prompt is not None
        assert "add a slack node" in proposal.anchored_prompt
        assert "'n1'" in proposal.anchored_prompt
        persisted = repo.append_chat_event.call_args.kwargs
        assert persisted["conversation_id"] == "c1"
        # Same proposal data rides the typed live frame and the persisted event;
        # the client dedupes the two copies by proposal_id.
        assert persisted["event"]["builder_prompt"] == proposal.model_dump(
            exclude_none=True,
        )
        assert persisted["event"]["timestamp"]

    async def test_background_spawns_headless_builder(self):
        # new=MagicMock: patch() would auto-substitute an AsyncMock for the
        # async target, and its call mints a coroutine the mocked spawn never
        # awaits (RuntimeWarning at teardown).
        with patch("utils.async_helpers.spawn") as spawn, \
             patch(
                 "nodes.agent.platform_tools._run_headless_builder_edit",
                 new=MagicMock(return_value="coro-stand-in"),
             ) as run:
            result = await prompt_builder_impl(
                pool=MagicMock(),
                user_id="u1", workflow_id="w1", node_id="n1",
                conversation_id="c1", conversation_key="telegram:99",
                prompt="add a slack node",
            )
        assert result["success"] is True
        assert result["status"] == "builder_started"
        spawn.assert_called_once()
        run.assert_called_once_with(
            user_id="u1", workflow_id="w1", node_id="n1", prompt="add a slack node",
            # The builder outcome relay's return address (builder_ask bridge
            # links + builder_result land on this conversation).
            agent_conversation_id="c1",
        )


class TestAgentNodeInjection:
    """The injection loop in agent_node.execute appends platform tools to the
    collected tool set. Pin the gating on the string-bool config field."""

    def test_enable_prompt_builder_config_default_true(self):
        from nodes.agent.config.base import BaseAgentFields

        field = BaseAgentFields.model_fields["enable_prompt_builder"]
        assert field.default == "true"

    def test_enable_email_updates_config_default_true(self):
        # email_user is ON by default (product call 2026-07-19); the per-node
        # unsubscribe link + settings toggle are the opt-out.
        from nodes.agent.config.base import BaseAgentFields

        field = BaseAgentFields.model_fields["enable_email_updates"]
        assert field.default == "true"

    def test_disabled_string_excludes_prompt_builder(self):
        # The injection site gates on config.enable_prompt_builder != "false".
        assert _tool_names(build_platform_tools("false" != "false")) == [
            SUBMIT_FEEDBACK_TOOL,
        ]


def _check_constraint_values(sql: str, column: str, constraint: str = ""):
    """Values a `CHECK` on `column` allows, however the file spells it.

    Migrations written by hand say `CHECK (col IN ('a', 'b'))`; a schema dumped
    with pg_dump says `CHECK ((col = ANY (ARRAY['a'::text, 'b'::text])))`. The
    open edition ships a dump, so a regex that only knows the first spelling
    reports "no migration defines the constraint" for one that is right there.
    """
    import re

    if constraint:
        # Anchor on the constraint's own name where we know it. Searching by
        # column alone takes the LAST match in the file, and a dumped schema has
        # a `type` CHECK on half a dozen tables.
        named = re.search(
            rf"CONSTRAINT {re.escape(constraint)} CHECK \(\(?{re.escape(column)}"
            rf"(?: IN \(([^)]+)\)| = ANY \(ARRAY\[([^\]]+)\])",
            sql, re.DOTALL,
        )
        if named:
            raw = named.group(1) or named.group(2)
            return {
                v.strip().strip("'").split("::")[0].strip().strip("'")
                for v in raw.split(",")
            }

    for pattern in (
        rf"CHECK \({re.escape(column)} IN \(([^)]+)\)",
        rf"{re.escape(column)} = ANY \(ARRAY\[([^\]]+)\]",
    ):
        found = None
        for match in re.finditer(pattern, sql, re.DOTALL):
            found = {
                v.strip().strip("'").split("::")[0].strip().strip("'")
                for v in match.group(1).split(",")
            }
        if found:
            return found
    return None


def test_every_trigger_source_is_allowed_by_the_db_check_constraint():
    """Third recurrence of this bug class (agent_turn 2026-06-30, shared_agent
    2026-07-10, builder_event + agent_email_reply 2026-07-19): a trigger_source
    literal written by backend code bounced on workflow_executions_trigger_
    source_check, silently killing wake-turns. Pin code vs schema: every
    literal in the codebase must appear in the LATEST migration defining the
    constraint."""
    import re
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    written = set()
    literal = re.compile(r"""trigger_source=["']([a-z_]+)["']""")
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith(("tests/", "debug_")) or "/tests/" in rel:
            continue
        written.update(literal.findall(path.read_text(errors="ignore")))
    assert written, "no trigger_source literals found — scan broke"

    migrations = Path(__file__).resolve().parents[2] / "infra" / "supabase" / "migrations"
    latest_allowed = None
    for path in sorted(migrations.glob("*.sql")):
        found = _check_constraint_values(
            path.read_text(), "trigger_source",
            "workflow_executions_trigger_source_check")
        if found:
            latest_allowed = found
    assert latest_allowed, "no migration defines the trigger_source CHECK"
    missing = written - latest_allowed
    assert not missing, (
        f"trigger_source values {missing} are written by the backend but "
        f"rejected by workflow_executions_trigger_source_check — add a "
        f"migration extending the constraint"
    )


def test_every_feedback_type_is_allowed_by_the_db_check_constraint():
    """The submit_feedback tool's type must satisfy the user_feedback CHECK.

    Pin code vs schema:
    each type the backend knows must appear in the LATEST migration that
    defines the constraint."""
    from pathlib import Path

    from utils.feedback import TYPE_LABELS

    migrations = Path(__file__).resolve().parents[2] / "infra" / "supabase" / "migrations"
    latest_allowed = None
    for path in sorted(migrations.glob("*.sql")):
        sql = path.read_text()
        if "user_feedback" not in sql:
            continue
        found = _check_constraint_values(sql, "type", "user_feedback_type_check")
        if found:
            latest_allowed = found
    assert latest_allowed, "no migration defines the user_feedback type CHECK"
    missing = set(TYPE_LABELS) - latest_allowed
    assert not missing, (
        f"feedback types {missing} are written by the backend but rejected by "
        f"user_feedback_type_check — add a migration extending the constraint"
    )


class TestBuilderRespond:
    async def test_answers_resume_the_parked_run_and_consume_the_link(self):
        from nodes.agent.platform_tools import builder_respond_impl

        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={
            "ask": {"relay_id": "link-1", "ask_id": "ask-1"},
        })
        link = {"id": "link-1", "builder_conversation_id": "agent-builder:w:n:x",
                "ask_id": "ask-1"}
        resumed = {}

        class FakeHandler:
            def __init__(self, sio):
                pass

            async def handle_input_response(self, sid, data, caller_user_id=None):
                resumed.update({"sid": sid, "caller": caller_user_id, **data})

        spawned = []
        with patch("repositories.builder_bridge.BuilderBridgeRepo.load_pending",
                   new=AsyncMock(return_value=link)), \
             patch("repositories.builder_bridge.BuilderBridgeRepo.mark_answered",
                   new=AsyncMock(return_value=True)) as marked, \
             patch("utils.socket_singleton.get_sio", new=lambda: MagicMock()), \
             patch("wss.handlers.workflow_builder_handler.WorkflowBuilderHandler", new=FakeHandler), \
             patch("utils.async_helpers.spawn", new=lambda coro, name=None: spawned.append(coro)):
            result = await builder_respond_impl(
                pool, user_id="owner", workflow_id="w1", conversation_id="ck:w:n:tg:9",
                answers={"ask_0": "#alerts"}, message="post daily at 9am",
            )
            assert spawned
            import asyncio
            await asyncio.gather(*spawned)

        assert result["success"] is True and result["status"] == "answers_submitted"
        assert marked.await_count == 1  # exactly-once vs a racing bridge submit
        assert resumed["sid"] == "" and resumed["caller"] == "owner"
        assert resumed["conversation_id"] == "agent-builder:w:n:x"
        assert resumed["ask_id"] == "ask-1"
        assert resumed["values"] == {"ask_0": "#alerts"}
        assert resumed["message"] == "post daily at 9am"

    async def test_already_answered_ask_is_refused(self):
        from nodes.agent.platform_tools import builder_respond_impl

        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"ask": {"relay_id": "link-1"}})
        with patch("repositories.builder_bridge.BuilderBridgeRepo.load_pending",
                   new=AsyncMock(return_value=None)):
            result = await builder_respond_impl(
                pool, user_id="o", workflow_id="w", conversation_id="c",
                answers={"a": "b"}, message=None,
            )
        assert result["success"] is False
        assert "already answered" in result["error"]

    async def test_empty_args_rejected(self):
        from nodes.agent.platform_tools import builder_respond_impl

        result = await builder_respond_impl(
            MagicMock(), user_id="o", workflow_id="w", conversation_id="c",
            answers=None, message="  ",
        )
        assert result["success"] is False


class TestDescribeWorkflow:
    async def test_returns_brain_snapshot_with_anchored_notes(self):
        from nodes.agent.platform_tools import describe_workflow_impl

        workflow = {
            "nodes": [
                {"id": "agent_1", "type": "agent", "data": {"config": {}}},
                {"id": "slack_1", "type": "automation-slack",
                 "data": {"config": {"agent_tool_operations": ["send_message"]}}},
                {"id": "tg_1", "type": "automation-telegram", "data": {"config": {}}},
                {"id": "sheet_1", "type": "automation-google-sheets", "data": {"config": {}}},
            ],
            "edges": [
                {"source": "tg_1", "target": "agent_1"},
                {"source": "slack_1", "target": "agent_1", "targetHandle": "bottom"},
                {"source": "agent_1", "target": "sheet_1"},
            ],
        }
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"name": "Bot", "workflow": workflow})
        result = await describe_workflow_impl(
            pool, user_id="u", workflow_id="w", node_id="agent_1",
        )
        assert result["success"] is True
        assert "<workflow>" in result["snapshot"]
        notes = "\n".join(result["position_notes"])
        assert "tg_1 (automation-telegram)" in notes            # trigger in
        assert "slack_1 (automation-slack; allowlisted ops: send_message)" in notes
        assert "sheet_1 (automation-google-sheets)" in notes    # downstream
        assert "breaks them" in notes
        # The graph shows wired capability only — the ambient-tools note stops
        # "no email node in the graph" reading as "cannot email" (2026-07-19).
        assert "NOT graph nodes" in notes
        assert "prompt_builder" in notes
        # Unset flag = ON by default: pre-feature configs get the tool too.
        assert "email_user" in notes and "needs NO email node" in notes

    async def test_ambient_note_reflects_capability_flags(self):
        from nodes.agent.platform_tools import describe_workflow_impl

        workflow = {
            "nodes": [{"id": "agent_1", "type": "agent", "data": {"config": {
                "enable_email_updates": "false", "enable_prompt_builder": "false",
            }}}],
            "edges": [],
        }
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"name": "Bot", "workflow": workflow})
        result = await describe_workflow_impl(
            pool, user_id="u", workflow_id="w", node_id="agent_1",
        )
        notes = "\n".join(result["position_notes"])
        assert "email_user" not in notes  # explicitly unsubscribed/toggled off
        assert "prompt_builder" not in notes  # builder capability off
        assert "submit_feedback" in notes  # always ambient

    async def test_ambient_note_does_not_claim_email_inside_iteration(self):
        from nodes.agent.platform_tools import describe_workflow_impl

        workflow = {
            "nodes": [{"id": "agent_1", "type": "agent", "data": {"config": {}}}],
            "edges": [],
        }
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value={"name": "Bot", "workflow": workflow})
        result = await describe_workflow_impl(
            pool, user_id="u", workflow_id="w", node_id="agent_1",
            in_iteration=True,
        )
        notes = "\n".join(result["position_notes"])
        assert "submit_feedback" in notes
        assert "email_user" not in notes

    async def test_missing_context_and_workflow(self):
        from nodes.agent.platform_tools import describe_workflow_impl

        assert (await describe_workflow_impl(
            MagicMock(), user_id=None, workflow_id="w", node_id="n"))["success"] is False
        pool = MagicMock()
        pool.fetchrow = AsyncMock(return_value=None)
        assert (await describe_workflow_impl(
            pool, user_id="u", workflow_id="w", node_id="n"))["success"] is False
