"""
Trigger-event delivery to agents (resolve_agent_event hook +
AgentNode._resolve_trigger_event).

When a run is started by a trigger wired directly into an agent, the fired
trigger's output is translated by its class's ``resolve_agent_event`` into
``{text, conversation_key}`` and delivered as part of the agent's user turn.
The fired trigger is identified by ``_triggerPayload`` in its config — the
marker only the webhook/trigger routes set — so manual runs deliver nothing
and stale trigger outputs preloaded from previous runs can't inject events.
"""

import json

import pytest
from unittest.mock import AsyncMock, patch

from nodes.agent_node import AgentNode
from nodes.alarm_node import AlarmNode
from nodes.core.base import WorkflowNode
from nodes.slack_node import SlackNode
from nodes.telegram_node import TelegramNode
from nodes.webhook_trigger_node import WebhookTriggerNode


def _make_agent(**kwargs) -> AgentNode:
    return AgentNode(
        node_id='agent_1',
        node_type='agent',
        node_data={},
        config=None,
        sio=None,
        sid=None,
        workflow_id='test_wf',
        **kwargs,
    )


def _wire(agent: AgentNode, nodes, edges) -> None:
    agent._workflow_nodes = nodes
    agent._workflow_edges = edges


class TestResolveAgentEventHook:
    """Per-class translation of a fired trigger's output into an agent event."""

    def test_default_delivers_unwrapped_payload_as_json(self):
        # The delivery envelope (type/status/_webhook plumbing) is not the
        # event: the payload wrapper is unwrapped and empties are pruned.
        output = {
            'type': 'webhook-trigger',
            'payload': {'issue': {'id': 7, 'labels': [], 'assignee': None}},
            '_webhook': {'headers': {'x-secret': 'y'}},
        }
        event = WebhookTriggerNode.resolve_agent_event(output)
        assert event['conversation_key'] is None
        assert json.loads(event['text']) == {'issue': {'id': 7}}
        assert 'x-secret' not in event['text']

    def test_default_names_the_event_and_bounds_the_body(self):
        output = {'type': 'x', 'event_type': 'issues', 'data': {'body': 'y' * 10_000}}
        event = WorkflowNode.resolve_agent_event(output)
        assert event['text'].startswith('Event: issues\n')
        assert len(event['text']) < 4300
        assert 'truncated' in event['text']

    def test_default_is_base_implementation(self):
        # Any node class without an override inherits the safe JSON default.
        assert 'resolve_agent_event' in WorkflowNode.__dict__

    def test_telegram_message_text_and_chat_key(self):
        update = {
            'update_id': 1,
            'message': {
                'text': 'hello agent',
                'chat': {'id': 100000001, 'title': 'Dev Chat'},
                'from': {'username': 'alex_example', 'first_name': 'Alex'},
            },
        }
        event = TelegramNode.resolve_agent_event(update)
        assert event['conversation_key'] == '100000001'
        assert 'hello agent' in event['text']
        assert 'alex_example' in event['text']
        assert '100000001' in event['text']  # reply id visible to the agent

    def test_telegram_caption_fallback(self):
        update = {
            'message': {
                'caption': 'look at this',
                'chat': {'id': 42},
                'from': {'first_name': 'A'},
            },
        }
        event = TelegramNode.resolve_agent_event(update)
        assert 'look at this' in event['text']
        assert event['conversation_key'] == '42'

    def test_telegram_non_message_update_falls_back_to_json(self):
        update = {'update_id': 2, 'my_chat_member': {'chat': {'id': 9}}}
        event = TelegramNode.resolve_agent_event(update)
        assert event['conversation_key'] is None
        assert json.loads(event['text']) == update

    def test_slack_channel_message_threads_conversation(self):
        output = {
            'type': 'slack',
            'data': {
                'event': {
                    'type': 'message',
                    'text': 'deploy please',
                    'channel': 'C123',
                    'ts': '1718000000.000100',
                    'user': 'U456',
                    'channel_type': 'channel',
                },
            },
        }
        event = SlackNode.resolve_agent_event(output)
        # Top-level message keys on channel:thread-root — replies in its
        # thread continue the same conversation.
        assert event['conversation_key'] == 'C123:1718000000.000100'
        assert 'deploy please' in event['text']
        assert 'C123' in event['text']  # reply ids visible to the agent

    def test_slack_thread_reply_keys_on_thread_root(self):
        output = {
            'type': 'slack',
            'data': {
                'event': {
                    'type': 'message',
                    'text': 'follow-up',
                    'channel': 'C123',
                    'ts': '1718000099.000200',
                    'thread_ts': '1718000000.000100',
                    'user': 'U456',
                },
            },
        }
        event = SlackNode.resolve_agent_event(output)
        assert event['conversation_key'] == 'C123:1718000000.000100'

    def test_slack_dm_keys_on_channel(self):
        output = {
            'type': 'slack',
            'data': {
                'event': {
                    'type': 'message',
                    'text': 'hi',
                    'channel': 'D789',
                    'ts': '1718000000.000100',
                    'channel_type': 'im',
                    'user': 'U456',
                },
            },
        }
        event = SlackNode.resolve_agent_event(output)
        assert event['conversation_key'] == 'D789'

    def test_slack_non_message_event_reads_as_one_line_plus_its_fields(self):
        output = {'type': 'slack', 'data': {
            'token': 'verification-secret', 'authorizations': [{'user_id': 'U0'}],
            'event': {'type': 'reaction_added', 'user': 'U1', 'reaction': 'eyes',
                      'item': {'type': 'message', 'channel': 'C1', 'ts': '1.0'}},
        }}
        event = SlackNode.resolve_agent_event(output)
        assert event['conversation_key'] == 'C1'
        assert event['text'].startswith('Slack reaction_added in channel C1:')
        assert '"reaction": "eyes"' in event['text']
        assert 'verification-secret' not in event['text']
        assert 'authorizations' not in event['text']

    def test_alarm_delivers_wake_message_and_scheduled_key(self):
        output = {
            'type': 'alarm_trigger',
            'message': 'Check stocks',
            'conversation_key': 'chat_789',
        }
        event = AlarmNode.resolve_agent_event(output)
        assert event == {'text': 'Check stocks', 'conversation_key': 'chat_789'}

    def test_alarm_without_message_delivers_nothing(self):
        assert AlarmNode.resolve_agent_event({'type': 'alarm_trigger'}) is None


class TestAgentResolveTriggerEvent:
    """The agent-side predicate: fired trigger + direct edge into this agent."""

    FIRED = {'_triggerPayload': {'some': 'payload'}}

    def test_fired_direct_trigger_delivers(self):
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {'id': 'wh1', 'type': 'trigger-webhook',
                 'config': {**self.FIRED, 'label': 'GitHub Issues'}},
                {'id': 'agent_1', 'type': 'agent', 'config': {}},
            ],
            edges=[{'source': 'wh1', 'target': 'agent_1'}],
        )
        inputs = {'wh1': {'type': 'webhook-trigger', 'payload': {'a': 1}}}

        event = agent._resolve_trigger_event(inputs)
        assert event is not None
        assert event['node_id'] == 'wh1'
        assert event['node_type'] == 'trigger-webhook'
        assert event['source'] == 'GitHub Issues'  # user label frames the event
        assert json.loads(event['text']) == {'a': 1}
        assert event['output'] is inputs['wh1']  # the chat record derives from it

    def test_source_falls_back_to_node_type(self):
        agent = _make_agent()
        _wire(
            agent,
            nodes=[{'id': 'wh1', 'type': 'trigger-webhook', 'config': dict(self.FIRED)},
                   {'id': 'agent_1', 'type': 'agent', 'config': {}}],
            edges=[{'source': 'wh1', 'target': 'agent_1'}],
        )
        event = agent._resolve_trigger_event({'wh1': {'x': 1}})
        assert event['source'] == 'trigger-webhook'

    def test_only_fired_trigger_delivers_among_many(self):
        """Three triggers wired into one agent; exactly the fired one delivers."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {'id': 'wh1', 'type': 'trigger-webhook', 'config': {}},
                {'id': 'wh2', 'type': 'trigger-webhook', 'config': dict(self.FIRED)},
                {'id': 'wh3', 'type': 'trigger-webhook', 'config': {}},
                {'id': 'agent_1', 'type': 'agent', 'config': {}},
            ],
            edges=[
                {'source': 'wh1', 'target': 'agent_1'},
                {'source': 'wh2', 'target': 'agent_1'},
                {'source': 'wh3', 'target': 'agent_1'},
            ],
        )
        # Stale outputs from previous runs preloaded for the siblings.
        inputs = {
            'wh1': {'payload': 'stale-1'},
            'wh2': {'payload': 'fresh'},
            'wh3': {'payload': 'stale-3'},
        }
        event = agent._resolve_trigger_event(inputs)
        assert event['node_id'] == 'wh2'
        assert 'fresh' in event['text']
        assert 'stale-1' not in event['text']

    def test_manual_run_delivers_nothing(self):
        """No _triggerPayload/_pollFired anywhere (run-from-node with preloaded
        upstream outputs — the poll never executed, so nothing stamped)."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[{'id': 'wh1', 'type': 'trigger-webhook', 'config': {}},
                   {'id': 'agent_1', 'type': 'agent', 'config': {}}],
            edges=[{'source': 'wh1', 'target': 'agent_1'}],
        )
        assert agent._resolve_trigger_event({'wh1': {'payload': 'cached'}}) is None

    def test_poll_fired_marker_delivers_on_manual_run(self):
        """A poll that executed THIS run and emitted fresh items (_pollFired,
        stamped by the executor) is a fired trigger on any run source — a
        manual run's fresh poll used to reach the agent with no event at all
        ('no payload was available', 2026-08-04)."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {'id': 'form', 'type': 'automation-google-forms',
                 'config': {'_pollFired': True, 'label': 'Contact Form'}},
                {'id': 'agent_1', 'type': 'agent', 'config': {}},
            ],
            edges=[{'source': 'form', 'target': 'agent_1'}],
        )
        inputs = {'form': {'responses': [{'responseId': 'r1', 'answers': {}}],
                           'new_response_count': 1}}
        event = agent._resolve_trigger_event(inputs)
        assert event is not None
        assert event['node_id'] == 'form'
        assert event['source'] == 'Contact Form'
        assert 'r1' in event['text']

    def test_preloaded_poll_output_without_marker_delivers_nothing(self):
        """The same fresh-looking output WITHOUT the run-scoped marker (a
        preloaded manifest from a previous run) must not masquerade as an
        event — stamping happens only right after execute()."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {'id': 'form', 'type': 'automation-google-forms', 'config': {}},
                {'id': 'agent_1', 'type': 'agent', 'config': {}},
            ],
            edges=[{'source': 'form', 'target': 'agent_1'}],
        )
        inputs = {'form': {'responses': [{'responseId': 'r1'}],
                           'new_response_count': 1}}
        assert agent._resolve_trigger_event(inputs) is None

    def test_indirect_trigger_delivers_nothing(self):
        """Trigger → transform → agent: not a direct edge, normal dataflow."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[
                {'id': 'wh1', 'type': 'trigger-webhook', 'config': dict(self.FIRED)},
                {'id': 'fn1', 'type': 'automation-serverless-function', 'config': {}},
                {'id': 'agent_1', 'type': 'agent', 'config': {}},
            ],
            edges=[
                {'source': 'wh1', 'target': 'fn1'},
                {'source': 'fn1', 'target': 'agent_1'},
            ],
        )
        assert agent._resolve_trigger_event({'wh1': {'payload': 1}, 'fn1': {'r': 2}}) is None

    def test_no_workflow_context_delivers_nothing(self):
        agent = _make_agent()
        assert agent._resolve_trigger_event({'wh1': {'payload': 1}}) is None

    def test_missing_output_delivers_nothing(self):
        """Fired trigger with no output in node_outputs (e.g. poll found nothing)."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[{'id': 'wh1', 'type': 'trigger-webhook', 'config': dict(self.FIRED)},
                   {'id': 'agent_1', 'type': 'agent', 'config': {}}],
            edges=[{'source': 'wh1', 'target': 'agent_1'}],
        )
        assert agent._resolve_trigger_event({}) is None

    def test_bottom_handle_edge_counts_as_direct(self):
        """Alarm wiring (top→bottom) is a direct edge for event delivery."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[{'id': 'al1', 'type': 'alarm', 'config': dict(self.FIRED)},
                   {'id': 'agent_1', 'type': 'agent', 'config': {}}],
            edges=[{'source': 'al1', 'target': 'agent_1', 'targetHandle': 'bottom'}],
        )
        inputs = {'al1': {'type': 'alarm_trigger', 'message': 'wake', 'conversation_key': 'k1'}}
        event = agent._resolve_trigger_event(inputs)
        assert event['text'] == 'wake'
        assert event['conversation_key'] == 'k1'

    def test_trigger_turn_persists_the_event_never_the_instructions(self):
        """The bubble and the conversation title are the EVENT: the standing
        instructions are node config. The record carries the fired node and
        its output with the delivery plumbing stripped and the size bounded."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[{'id': 'wh1', 'type': 'trigger-webhook',
                    'config': {**self.FIRED, 'label': 'Orders hook', 'operation': None}},
                   {'id': 'agent_1', 'type': 'agent', 'config': {}}],
            edges=[{'source': 'wh1', 'target': 'agent_1'}],
        )
        inputs = {'wh1': {'order': {'id': 7, 'note': ''}, 'title': 'Order 7',
                          '_webhook': {'headers': {'authorization': 'Bearer secret'}}}}
        event = agent._resolve_trigger_event(inputs)
        message, label, record = AgentNode._trigger_turn_record(event)
        assert message == event['text']
        assert 'Bearer secret' not in message
        assert label == json.dumps({'order': {'id': 7}, 'title': 'Order 7'}, indent=2).splitlines()[0]
        assert record['node_type'] == 'trigger-webhook'
        assert record['label'] == 'Orders hook'
        assert record['output'] == {'order': {'id': 7}, 'title': 'Order 7'}
        # A hook title names the conversation outright.
        message, label, _ = AgentNode._trigger_turn_record({**event, 'title': '#support'})
        assert label == '#support'

    def test_integration_trigger_with_an_override_delivers(self):
        """2026-08-03: a PostHog on_rageclick trigger wired into an agent killed
        the run — the override was declared as an instance method, and the hook
        is called on the CLASS ("missing 1 required positional argument:
        'output'"). Registry-wide guard: test_node_class_hook_contract.py."""
        agent = _make_agent()
        _wire(
            agent,
            nodes=[{'id': 'ph1', 'type': 'automation-posthog', 'config': dict(self.FIRED)},
                   {'id': 'agent_1', 'type': 'agent', 'config': {}}],
            edges=[{'source': 'ph1', 'target': 'agent_1'}],
        )
        inputs = {'ph1': {'status': 'success', 'action': 'on_rageclick',
                          'data': {'event': '$rageclick', 'distinct_id': 'u1'}}}
        event = agent._resolve_trigger_event(inputs)
        assert event['node_id'] == 'ph1'
        assert '$rageclick' in event['text']


class TestEventMedia:
    """What a message carried besides text rides the hook result as
    ``media`` entries (agent_events.media_entry) and the agent digests them
    into the turn — a voice note becomes a transcript, never a placeholder."""

    def test_discord_voice_message_is_a_voice_entry(self):
        from nodes.discord_node import DiscordNode

        output = {
            'type': 'discord', 'event_type': 'on_message', 'channel_id': 'c1',
            'author_username': 'dana', 'content': '', 'message_id': 'm1',
            'attachments': [{'url': 'https://cdn.discordapp.com/a/voice-message.ogg',
                             'filename': 'voice-message.ogg', 'content_type': 'audio/ogg',
                             'size': 9000, 'duration_secs': 6.5}],
        }
        event = DiscordNode.resolve_agent_event(output)
        assert '[voice message]' in event['text']
        (entry,) = event['media']
        assert entry['voice'] is True and entry['duration_s'] == 6.5
        assert entry['record'] is output['attachments'][0]

    def test_email_audio_attachment_is_an_entry_documents_are_inlined_instead(self):
        from nodes.inbound_email_trigger_node import InboundEmailTriggerNode

        output = {
            'from': 'a@example.com', 'to': 'agent@example.test', 'subject': 'memo', 'text': 'see attached',
            'attachments': [
                {'name': 'memo.m4a', 'mime_type': 'audio/mp4', 'size_bytes': 5000,
                 'download_url': 'https://assets.example/memo.m4a', 'resource_id': 'r-audio'},
                {'name': 'q.pdf', 'mime_type': 'application/pdf', 'size_bytes': 100,
                 'download_url': 'https://assets.example/q.pdf', 'resource_id': 'r-doc', 'text': 'inlined'},
            ],
        }
        event = InboundEmailTriggerNode.resolve_agent_event(output)
        assert 'Content of q.pdf' in event['text']
        (entry,) = event['media']
        assert entry['resource_id'] == 'r-audio' and entry['mime_type'] == 'audio/mp4'

    def test_resolve_trigger_event_carries_the_media_entries(self):
        agent = _make_agent()
        _wire(
            agent,
            nodes=[{'id': 'tg', 'type': 'automation-telegram', 'config': {'_triggerPayload': {}}},
                   {'id': 'agent_1', 'type': 'agent', 'config': {}}],
            edges=[{'source': 'tg', 'target': 'agent_1'}],
        )
        media = {'url': 'https://assets.example/v.oga', 'mimetype': 'audio/ogg', 'rehosted': True, 'resource_id': 'r1'}
        inputs = {'tg': {'message': {'chat': {'id': 5}, 'voice': {'file_id': 'f', 'duration': 3}, 'media': media}}}
        event = agent._resolve_trigger_event(inputs)
        assert event['media'][0]['record'] is media
        assert event['media'][0]['voice'] is True

    @pytest.mark.asyncio
    async def test_digest_composes_the_transcript_under_the_event_text(self):
        from nodes.core.media_digest import MediaDigest, MediaRef

        agent = _make_agent(user_id='u1')
        agent.conversation_id = 'conv-1'
        trigger_event = {
            'node_id': 'tg', 'node_type': 'automation-telegram', 'text': 'Telegram message:\n[voice message]',
            'media': [{'url': 'https://assets.example/v.oga', 'mime_type': 'audio/ogg', 'voice': True,
                       'duration_s': 3, 'record': {}}],
        }
        seen = {}

        async def fake_digest(refs, ctx):
            seen['ctx'] = ctx
            return [MediaDigest(ref=refs[0], text='call me back', method='transcription')]

        config = type('Cfg', (), {'enable_media_transcription': 'true'})()
        with patch('nodes.core.media_digest.digest_media', fake_digest):
            await agent._digest_event_media(trigger_event, config)
        assert trigger_event['text'].endswith('Voice message (0:03) — transcript:\n"""\ncall me back\n"""')
        assert seen['ctx'].billing.user_id == 'u1'
        assert seen['ctx'].workflow_id == 'test_wf'
        assert seen['ctx'].allow_ai is True

        # The agent's switch reaches the digest as allow_ai.
        config.enable_media_transcription = 'false'
        with patch('nodes.core.media_digest.digest_media', fake_digest):
            await agent._digest_event_media(dict(trigger_event, text='x'), config)
        assert seen['ctx'].allow_ai is False

    @pytest.mark.asyncio
    async def test_rehearsal_fetches_and_bills_nothing(self):
        agent = _make_agent(user_id='u1')
        agent.conversation_id = 'rehearsal:test_wf:abc'
        trigger_event = {
            'node_id': 'wa', 'node_type': 'automation-whatsapp', 'text': 'WhatsApp message:\n[voice message]',
            'media': [{'url': 'https://assets.example/v.oga', 'mime_type': 'audio/ogg', 'voice': True}],
        }
        with patch('nodes.core.media_digest.digest_media', AsyncMock(side_effect=AssertionError('must not digest'))):
            await agent._digest_event_media(trigger_event, type('Cfg', (), {})())
        assert 'not transcribed in a Test Run' in trigger_event['text']

    @pytest.mark.asyncio
    async def test_nothing_digestible_leaves_the_text_alone(self):
        agent = _make_agent(user_id='u1')
        trigger_event = {'node_id': 'x', 'node_type': 'trigger-webhook', 'text': 'hello', 'media': []}
        await agent._digest_event_media(trigger_event, type('Cfg', (), {})())
        assert trigger_event['text'] == 'hello'
