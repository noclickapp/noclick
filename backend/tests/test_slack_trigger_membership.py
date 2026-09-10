"""Slack channel triggers: registered ≠ receiving.

Slack delivers channel events (message.channels, app_mention, reaction_added,
member_joined_channel, file_shared) ONLY to apps that are members of the
channel. Registration used to write the subscription row and print
"Active — listening in the selected channel" with no membership check, so a
trigger on #support — two members, neither of them the app — sat green
and deaf (2026-09-10). Registration now judges membership, the Status field
carries the verdict, and a public channel gets a one-click join.
"""

import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from nodes.core.webhook_subscriptions import RegistrationAdvisory, registration_mirrors
from nodes.slack_node import SlackNode, _SlackChannelScopedTriggerBase

SLACK = "https://slack.com/api"
CRED = {"access_token": "xoxb-1", "team_id": "T1"}


def _slack(route: respx.Router, method: str, payload: dict, *, http: str = "GET"):
    return route.request(http, f"{SLACK}/{method}").mock(return_value=httpx.Response(200, json=payload))


# ─── which triggers need membership ──────────────────────────────────────────


def test_membership_ops_are_exactly_the_channel_scoped_triggers():
    """The set is derived from the trigger map; pin it to the config classes
    so a new channel-scoped trigger cannot ship without the check."""
    channel_scoped = set()
    for cls in _SlackChannelScopedTriggerBase.__subclasses__():
        channel_scoped.add(cls.model_fields["operation"].default)
    assert SlackNode._CHANNEL_MEMBERSHIP_TRIGGER_OPS == channel_scoped
    assert "on_channel_created" not in SlackNode._CHANNEL_MEMBERSHIP_TRIGGER_OPS


# ─── the verdict ─────────────────────────────────────────────────────────────


class TestCheckRegistrationHealth:
    async def test_workspace_wide_trigger_needs_no_membership(self):
        with respx.mock(assert_all_called=False) as route:
            info = _slack(route, "conversations.info", {"ok": False, "error": "boom"})
            assert await SlackNode.check_registration_health(CRED, "on_channel_created", {"channel": "C1"}) is None
        assert not info.called

    async def test_member_of_the_picked_channel_is_healthy(self):
        with respx.mock as route:
            _slack(route, "conversations.info", {"ok": True, "channel": {"id": "C1", "name": "support", "is_member": True}})
            assert await SlackNode.check_registration_health(CRED, "on_channel_message", {"channel": "C1"}) is None

    async def test_public_channel_without_the_app_offers_a_join(self):
        with respx.mock as route:
            _slack(route, "conversations.info", {"ok": True, "channel": {"id": "C1", "name": "support", "is_member": False, "is_private": False}})
            _slack(route, "auth.test", {"ok": True, "user": "noclick"})
            advisory = await SlackNode.check_registration_health(CRED, "on_channel_message", {"channel": "C1"})
        assert isinstance(advisory, RegistrationAdvisory)
        assert "@noclick isn't in #support" in advisory.message
        assert advisory.action == {"field": "join_channel", "label": "Join #support"}

    async def test_private_channel_without_the_app_needs_a_human_invite(self):
        """Slack has no API to self-invite into a private channel."""
        with respx.mock as route:
            _slack(route, "conversations.info", {"ok": True, "channel": {"id": "C1", "name": "leadership", "is_member": False, "is_private": True}})
            _slack(route, "auth.test", {"ok": True, "user": "noclick"})
            advisory = await SlackNode.check_registration_health(CRED, "on_app_mention", {"channel": "C1"})
        assert advisory.action is None
        assert "/invite @noclick" in advisory.message and "#leadership" in advisory.message

    async def test_channel_the_app_cannot_see_reads_as_a_private_one(self):
        """conversations.info answers channel_not_found for a private channel
        the app was never invited to — the picker's label names it."""
        with respx.mock as route:
            _slack(route, "conversations.info", {"ok": False, "error": "channel_not_found"})
            _slack(route, "auth.test", {"ok": False, "error": "nope"})
            advisory = await SlackNode.check_registration_health(
                CRED, "on_channel_message", {"channel": "C1", "channel__label": "#secret"}
            )
        assert advisory.action is None
        assert "the app isn't in #secret" in advisory.message and "/invite the app" in advisory.message

    async def test_archived_channel_is_named_as_such(self):
        with respx.mock as route:
            _slack(route, "conversations.info", {"ok": True, "channel": {"id": "C1", "name": "old", "is_member": False, "is_archived": True}})
            advisory = await SlackNode.check_registration_health(CRED, "on_channel_message", {"channel": "C1"})
        assert advisory.action is None and "#old is archived" in advisory.message

    async def test_no_channel_filter_needs_the_app_in_at_least_one_channel(self):
        with respx.mock as route:
            convs = _slack(route, "users.conversations", {"ok": True, "channels": [{"id": "C1"}]})
            assert await SlackNode.check_registration_health(CRED, "on_channel_message", {"channel": ""}) is None
        assert convs.calls[0].request.url.params["limit"] == "1"
        with respx.mock as route:
            _slack(route, "users.conversations", {"ok": True, "channels": []})
            _slack(route, "auth.test", {"ok": True, "user": "noclick"})
            advisory = await SlackNode.check_registration_health(CRED, "on_channel_message", {})
        assert advisory.action is None and "@noclick isn't in any channel yet" in advisory.message

    async def test_other_slack_errors_propagate_as_cannot_judge(self):
        with respx.mock as route:
            _slack(route, "conversations.info", {"ok": False, "error": "missing_scope"})
            with pytest.raises(ValueError, match="missing_scope"):
                await SlackNode.check_registration_health(CRED, "on_channel_message", {"channel": "C1"})


# ─── the mirrors every registration surface stamps ───────────────────────────


def test_registration_mirrors_shape():
    assert registration_mirrors("Active — x", None) == {
        "trigger_registered": True, "trigger_error": None,
        "subscription_status": "Active — x", "trigger_action": None,
    }
    action = {"field": "join_channel", "label": "Join #x"}
    assert registration_mirrors("Active — x", RegistrationAdvisory("deaf", action)) == {
        "trigger_registered": True, "trigger_error": "deaf",
        "subscription_status": "⚠ deaf", "trigger_action": action,
    }


class TestRegisterAndDescribe:
    def _kwargs(self):
        return dict(
            user_id="owner", workflow_id="wf", node_id="n1", operation="on_channel_message",
            credential_id="cred", credential=CRED, config={"channel": "C1"},
        )

    async def test_healthy_registration_stays_active(self):
        with patch.object(SlackNode, "register_node_subscriptions", AsyncMock(return_value="Active — listening in the selected channel")), \
             patch.object(SlackNode, "check_registration_health", AsyncMock(return_value=None)):
            mirrors = await SlackNode.register_and_describe(object(), **self._kwargs())
        assert mirrors["subscription_status"] == "Active — listening in the selected channel"
        assert mirrors["trigger_error"] is None and mirrors["trigger_action"] is None

    async def test_deaf_registration_carries_the_verdict_and_the_fix(self):
        advisory = RegistrationAdvisory("@noclick isn't in #x", {"field": "join_channel", "label": "Join #x"})
        with patch.object(SlackNode, "register_node_subscriptions", AsyncMock(return_value="Active")), \
             patch.object(SlackNode, "check_registration_health", AsyncMock(return_value=advisory)):
            mirrors = await SlackNode.register_and_describe(object(), **self._kwargs())
        assert mirrors == {
            "trigger_registered": True, "trigger_error": "@noclick isn't in #x",
            "subscription_status": "⚠ @noclick isn't in #x",
            "trigger_action": {"field": "join_channel", "label": "Join #x"},
        }

    async def test_probe_failure_is_cannot_judge_not_an_accusation(self, caplog):
        """A network blip must not turn a working trigger red, nor fail the
        registration that just succeeded."""
        with patch.object(SlackNode, "register_node_subscriptions", AsyncMock(return_value="Active")), \
             patch.object(SlackNode, "check_registration_health", AsyncMock(side_effect=httpx.ConnectError("down"))), \
             caplog.at_level(logging.WARNING):
            mirrors = await SlackNode.register_and_describe(object(), **self._kwargs())
        assert mirrors["subscription_status"] == "Active" and mirrors["trigger_error"] is None
        assert "health probe failed" in caplog.text

    async def test_a_broken_probe_is_logged_loudly(self, caplog):
        with patch.object(SlackNode, "register_node_subscriptions", AsyncMock(return_value="Active")), \
             patch.object(SlackNode, "check_registration_health", AsyncMock(side_effect=AttributeError("typo"))), \
             caplog.at_level(logging.ERROR):
            mirrors = await SlackNode.register_and_describe(object(), **self._kwargs())
        assert mirrors["trigger_error"] is None
        assert "health probe is broken" in caplog.text


# ─── the fix-it action ───────────────────────────────────────────────────────


class TestJoinChannelAction:
    def _load(self, context):
        return SlackNode.load_field_value(
            "join_channel", user_id="u1", workflow_id="6c0f4e2a-9b1d-4c3e-8f5a-2d7b1e9c4a10", node_id="n1", pool=object(),
            context=context, credential_ids={"slack_oauth": "cred"},
        )

    async def test_join_then_re_register_through_the_status_path(self):
        """Join, re-run the status registration, and persist its mirrors —
        the Dashboard runs this away from the panel, so nothing else would."""
        from utils.webhook_manager import WebhookManager

        mirrors = {"subscription_status": "Active", "trigger_error": None, "trigger_action": None}
        with respx.mock as route:
            join = _slack(route, "conversations.join", {"ok": True}, http="POST")
            with patch.object(SlackNode, "_resolve_trigger_credential", AsyncMock(return_value=("cred", CRED))), \
                 patch("nodes.core.webhook_subscriptions.AppEventTriggerMixin.load_field_value",
                       AsyncMock(return_value={"values": mirrors})) as status_load, \
                 patch.object(WebhookManager, "merge_node_config_patch", AsyncMock()) as merge:
                result = await self._load({"channel": "C1", "operation": "on_channel_message"})
        assert join.calls[0].request.content == b"channel=C1"
        assert result == {"values": mirrors}
        assert status_load.await_args.args[0] == "subscription_status"
        assert merge.await_args.args[2:] == ("n1", mirrors)

    async def test_join_failure_stays_on_the_status_field_with_the_retry(self):
        with respx.mock as route:
            _slack(route, "conversations.join", {"ok": False, "error": "is_archived"}, http="POST")
            with patch.object(SlackNode, "_resolve_trigger_credential", AsyncMock(return_value=("cred", CRED))):
                result = await self._load({"channel": "C1", "channel__label": "#old"})
        assert result["values"]["subscription_status"] == "⚠ Couldn't join #old: is_archived"
        assert result["values"]["trigger_action"] == {"field": "join_channel", "label": "Join #old"}

    async def test_join_needs_a_channel_and_a_credential(self):
        with pytest.raises(ValueError, match="Pick a channel"):
            await self._load({})
        with patch.object(SlackNode, "_resolve_trigger_credential", AsyncMock(return_value=(None, None))):
            with pytest.raises(ValueError, match="Connect a credential"):
                await self._load({"channel": "C1"})

    async def test_other_fields_still_reach_the_mixin(self):
        with patch("nodes.core.webhook_subscriptions.AppEventTriggerMixin.load_field_value",
                   AsyncMock(return_value={"value": None})) as base:
            await SlackNode.load_field_value("webhook_url", user_id="u", workflow_id="wf", node_id="n", pool=object())
        assert base.await_args.args[0] == "webhook_url"


# ─── what the brain reads ────────────────────────────────────────────────────


def test_builder_line_says_registered_but_not_receiving():
    from coder.workflow.operation_catalog import trigger_status_line

    line = trigger_status_line(
        "automation-slack", "on_channel_message",
        {"trigger_registered": True, "trigger_error": "@noclick isn't in #support",
         "subscription_status": "⚠ @noclick isn't in #support"},
    )
    assert "registered but NOT receiving events" in line and "#support" in line
