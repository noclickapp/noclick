"""Regression tests for the three headless-build gaps diagnosed from builder
run 00000000-0000-4000-8000-000000000001 ("Example Chat Assistant"):

1. An agent's model flip to a CLI harness via a brain <field> op never
   re-evaluated the credential requirement (#1619 only re-checks after node drafter),
   so the build finished with model=openclaw and no credential attached.
2. The agentic builder never provisioned trigger webhooks — the Telegram
   trigger's webhooks row + provider registration only happened when the user
   opened the node's config panel in the UI.
3. node drafter templated {{ $('telegram-trigger').message }} into the agent's
   message (the fired event is delivered automatically), so the first run
   failed config validation on the non-string payload object.
"""

import pytest

from coder.workflow.agentic.commands import (
    credential_recheck_ids,
    execute_field_ops,
    nodes_missing_credentials,
)
from coder.workflow.graph_state import GraphState, NodeState
from coder.workflow.workflow_ops import (
    DEFAULT_AGENT_STANDING_MESSAGE,
    drop_stale_agent_discriminator,
    is_trigger_source,
    strip_agent_trigger_message_refs,
)
from coder.workflow.workflow_xml import XmlOp
from nodes.agent.config.providers import (
    HARNESS_SUBMODEL_FIELDS,
    WRAPPER_ID_BY_MODEL_TYPE,
    agent_credential_requirement,
)


def _field_op(node, name, value):
    return XmlOp(tag='field', attrs={'node': node, 'name': name, 'value': value}, body=None)


def _agent_state(node_id='openclaw-agent', config=None, parent_ids=None):
    state = GraphState()
    state.nodes[node_id] = NodeState(
        id=node_id, type='agent', label='Agent', goal='Personal assistant',
        operation='default', config=dict(config or {}),
        parent_ids=list(parent_ids or []),
    )
    return state


# ============================================================================
# 1. Harness credential re-check on <field> model flips
# ============================================================================

class TestCredentialRecheckIds:
    def test_model_flip_on_agent_is_relevant(self):
        state = _agent_state()
        ops = [_field_op('openclaw-agent', 'model', 'openclaw')]
        assert credential_recheck_ids(ops, state) == ['openclaw-agent']

    @pytest.mark.parametrize('submodel_field', sorted(HARNESS_SUBMODEL_FIELDS.values()))
    def test_harness_submodel_fields_are_relevant(self, submodel_field):
        state = _agent_state()
        ops = [_field_op('openclaw-agent', submodel_field, 'anthropic/claude-x')]
        assert credential_recheck_ids(ops, state) == ['openclaw-agent']

    def test_operation_change_is_relevant_on_any_node(self):
        state = GraphState()
        state.nodes['tg'] = NodeState(
            id='tg', type='automation-telegram', label='TG', goal='trigger',
            operation='send_message_to_chat',
        )
        ops = [_field_op('tg', 'operation', 'receive_webhook_messages')]
        assert credential_recheck_ids(ops, state) == ['tg']

    def test_ordinary_fields_are_not_relevant(self):
        state = _agent_state()
        ops = [
            _field_op('openclaw-agent', 'temperature', '0.5'),
            _field_op('openclaw-agent', 'system_prompt', 'be nice'),
        ]
        assert credential_recheck_ids(ops, state) == []

    def test_unknown_node_ignored(self):
        state = _agent_state()
        ops = [_field_op('ghost', 'model', 'openclaw')]
        assert credential_recheck_ids(ops, state) == []


class TestModelFlipDropsStaleDiscriminator:
    """A stale model_type next to a new model must never mis-route the
    credential predicate (llm variant → 'platform key, no credential')."""

    def test_execute_field_ops_drops_model_type(self):
        state = _agent_state(config={
            'model': 'openrouter/~openai/gpt-mini-latest', 'model_type': 'llm',
            'message': 'hi',
        })
        execute_field_ops([_field_op('openclaw-agent', 'model', 'openclaw')], state)
        cfg = state.nodes['openclaw-agent'].config
        assert cfg['model'] == 'openclaw'
        assert 'model_type' not in cfg
        req = agent_credential_requirement(cfg)
        assert req.required is True

    def test_helper_noops_when_model_type_also_written(self):
        cfg = {'model': 'x', 'model_type': 'image'}
        drop_stale_agent_discriminator('agent', {'model', 'model_type'}, cfg)
        assert cfg['model_type'] == 'image'

    @pytest.mark.parametrize('order', ['type_first', 'model_first'])
    def test_batch_setting_both_keeps_explicit_discriminator(self, order):
        """One batch writing model AND model_type must keep the explicit
        discriminator regardless of op order (the drop is batch-aware)."""
        state = _agent_state(config={'message': 'hi'})
        ops = [
            _field_op('openclaw-agent', 'model_type', 'image'),
            _field_op('openclaw-agent', 'model', 'openrouter/some/image-model'),
        ]
        if order == 'model_first':
            ops.reverse()
        execute_field_ops(ops, state)
        assert state.nodes['openclaw-agent'].config.get('model_type') == 'image'

    def test_helper_noops_for_non_agent(self):
        cfg = {'model': 'x', 'model_type': 'llm'}
        drop_stale_agent_discriminator('automation-slack', {'model'}, cfg)
        assert cfg['model_type'] == 'llm'


class TestEveryHarnessRequiresCredential:
    """The fix must hold for every CLI harness, not just openclaw."""

    @pytest.mark.parametrize('wrapper_id', sorted(WRAPPER_ID_BY_MODEL_TYPE.values()))
    def test_harness_flip_yields_required(self, wrapper_id):
        cfg = {'model': 'openrouter/~openai/gpt-mini-latest', 'model_type': 'llm'}
        drop_stale_agent_discriminator('agent', {'model'}, cfg)
        cfg['model'] = wrapper_id
        req = agent_credential_requirement(cfg)
        assert req.required is True, wrapper_id
        assert req.credential_type.startswith('agent_'), wrapper_id


class TestNodesMissingCredentials:
    def test_uncredentialed_harness_agent_listed(self):
        state = _agent_state(config={'model': 'openclaw', 'message': 'hi'})
        assert [n.id for n in nodes_missing_credentials(state)] == ['openclaw-agent']

    def test_credentialed_agent_not_listed(self):
        state = _agent_state(config={
            'model': 'openclaw', 'message': 'hi',
            'credentialIds': {'agent_anthropic': 'cred-1'},
        })
        assert nodes_missing_credentials(state) == []

    def test_platform_billed_agent_not_listed(self):
        state = _agent_state(config={
            'model': 'openrouter/~openai/gpt-mini-latest', 'message': 'hi',
        })
        assert nodes_missing_credentials(state) == []

    def test_disabled_node_not_listed(self):
        state = _agent_state(config={
            'model': 'openclaw', 'message': 'hi', 'disabled': True,
        })
        assert nodes_missing_credentials(state) == []


class TestAutoselectSingleCredentials:
    """Auto-attach across all accepted types, with primary-type preference."""

    class _Platform:
        def __init__(self, creds_by_type):
            self.creds_by_type = creds_by_type
            self.authorized = []

        async def search_credentials(self, cred_type, query, limit):
            return list(self.creds_by_type.get(cred_type, []))

        async def authorize_credentials(self, ids):
            self.authorized.extend(ids)

    # openclaw's default sub-model rides OpenRouter, so its requirement is
    # primary=agent_openrouter with agent_api_key also accepted — derive both
    # from the predicate so the test tracks the real billing rule.
    @staticmethod
    def _types():
        req = agent_credential_requirement({'model': 'openclaw'})
        primary = req.credential_type
        secondary = next(t for t in req.accepted_types if t != primary)
        return primary, secondary

    @staticmethod
    def _harness_state():
        return _agent_state(config={'model': 'openclaw', 'message': 'hi'})

    async def _run(self, state, creds_by_type):
        from coder.workflow.agentic.commands import autoselect_single_credentials
        platform = self._Platform(creds_by_type)
        attached = await autoselect_single_credentials(
            list(state.nodes.keys()), state, platform,
        )
        return attached, platform

    @pytest.mark.asyncio
    async def test_sole_primary_credential_attaches(self):
        primary, _ = self._types()
        state = self._harness_state()
        attached, platform = await self._run(state, {primary: [{'id': 'cred-a'}]})
        assert attached == ['openclaw-agent']
        cred_ids = state.nodes['openclaw-agent'].config['credentialIds']
        assert cred_ids == {primary: 'cred-a'}
        assert platform.authorized == ['cred-a']

    @pytest.mark.asyncio
    async def test_sole_secondary_type_credential_attaches(self):
        # User's only satisfying credential is a non-primary accepted type.
        primary, secondary = self._types()
        state = self._harness_state()
        attached, _ = await self._run(state, {secondary: [{'id': 'cred-o'}]})
        assert attached == ['openclaw-agent']
        cred_ids = state.nodes['openclaw-agent'].config['credentialIds']
        assert cred_ids == {secondary: 'cred-o'}

    @pytest.mark.asyncio
    async def test_primary_preferred_over_secondary(self):
        # One of EACH accepted type: the primary wins (no ambiguity prompt).
        primary, secondary = self._types()
        state = self._harness_state()
        attached, _ = await self._run(state, {
            primary: [{'id': 'cred-a'}],
            secondary: [{'id': 'cred-o'}],
        })
        assert attached == ['openclaw-agent']
        cred_ids = state.nodes['openclaw-agent'].config['credentialIds']
        assert cred_ids == {primary: 'cred-a'}

    @pytest.mark.asyncio
    async def test_ambiguous_secondaries_left_unattached(self):
        _, secondary = self._types()
        state = self._harness_state()
        attached, _ = await self._run(state, {
            secondary: [{'id': 'c1'}, {'id': 'c2'}],
        })
        assert attached == []
        assert 'credentialIds' not in state.nodes['openclaw-agent'].config


class TestDoneGateNudge:
    """<done/> with a credential-requiring node uncredentialed gets one nudge."""

    @staticmethod
    def _builder(messages, graph_state):
        from coder.workflow.agentic.builder import AgenticBuilder
        b = object.__new__(AgenticBuilder)
        b.messages = messages
        b.graph_state = graph_state
        return b

    _EXEC = {'role': 'user', 'content': '[System: Execution Result]\nGraph changes: ...'}

    def test_nudges_once_for_missing_credentials(self):
        state = _agent_state(config={'model': 'openclaw', 'message': 'hi'})
        b = self._builder([self._EXEC], state)
        nudge = b._credential_done_nudge()
        assert nudge and 'openclaw-agent' in nudge
        assert b._CRED_NUDGE_MARKER in nudge

    def test_no_renudge_after_marker_in_history(self):
        state = _agent_state(config={'model': 'openclaw', 'message': 'hi'})
        b = self._builder(
            [self._EXEC, {'role': 'user', 'content': '[System: Credential check]\n...'}],
            state,
        )
        assert b._credential_done_nudge() is None

    def test_no_nudge_on_pure_conversation(self):
        state = _agent_state(config={'model': 'openclaw', 'message': 'hi'})
        b = self._builder([{'role': 'user', 'content': 'what does this do?'}], state)
        assert b._credential_done_nudge() is None

    def test_no_nudge_when_credentialed(self):
        state = _agent_state(config={
            'model': 'openclaw', 'message': 'hi',
            'credentialIds': {'agent_anthropic': 'cred-1'},
        })
        b = self._builder([self._EXEC], state)
        assert b._credential_done_nudge() is None

    def test_gate_holds_turn_open_when_credentials_missing(self):
        """The shared gate both exits use. Before this existed, a brain that
        bundled <done/> with <field> ops summarized in prose on the next turn
        and finalized without any credential check (2026-07-29 exa incident)."""
        state = _agent_state(config={'model': 'openclaw', 'message': 'hi'})
        b = self._builder([self._EXEC], state)
        assert b._gate_on_missing_credentials('Pure text exit') is True
        assert b.messages[-1]['content'].startswith(b._CRED_NUDGE_MARKER)
        assert b._last_turn_result.next_action == 'continue'

    def test_gate_passes_when_nothing_missing(self):
        state = _agent_state(config={
            'model': 'openclaw', 'message': 'hi',
            'credentialIds': {'agent_anthropic': 'cred-1'},
        })
        b = self._builder([self._EXEC], state)
        assert b._gate_on_missing_credentials('Done') is False
        assert b.messages == [self._EXEC]


# ============================================================================
# 2. Headless webhook provisioning
# ============================================================================

class TestProvisionNodeWebhook:
    @pytest.mark.asyncio
    async def test_custom_loader_invoked_for_trigger_op(self, monkeypatch):
        from nodes.telegram_node import TelegramNode
        from utils.webhook_manager import WebhookManager

        calls = {}

        async def fake_loader(**kwargs):
            calls.update(kwargs)
            return {'values': {'webhook_url': 'https://wh.hooks.example.test',
                               'telegram_registered': False,
                               'telegram_error': 'Bot token not configured'}}

        monkeypatch.setattr(TelegramNode, 'load_field_value', staticmethod(fake_loader))
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='telegram-trigger', node_type='automation-telegram',
            operation='receive_webhook_messages', config={},
        )
        assert updates['webhook_url'] == 'https://wh.hooks.example.test'
        assert calls['field_name'] == 'webhook_url'
        assert calls['node_id'] == 'telegram-trigger'

    @pytest.mark.asyncio
    async def test_custom_loader_reinvoked_when_url_already_set(self, monkeypatch):
        """A credential attach must re-run provider registration even though
        the row/url already exist — the panel does the same on every open."""
        from nodes.telegram_node import TelegramNode
        from utils.webhook_manager import WebhookManager

        invoked = []

        async def fake_loader(**kwargs):
            invoked.append(kwargs['credential_ids'])
            return {'values': {'webhook_url': 'https://wh.hooks.example.test',
                               'telegram_registered': True}}

        monkeypatch.setattr(TelegramNode, 'load_field_value', staticmethod(fake_loader))
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='telegram-trigger', node_type='automation-telegram',
            operation='receive_webhook_messages',
            config={'webhook_url': 'https://wh.hooks.example.test',
                    'credentialIds': {'telegram_bot_token': 'cred-1'}},
        )
        assert invoked == [{'telegram_bot_token': 'cred-1'}]
        assert updates['telegram_registered'] is True

    @pytest.mark.asyncio
    async def test_non_trigger_operation_skipped(self, monkeypatch):
        from nodes.telegram_node import TelegramNode
        from utils.webhook_manager import WebhookManager

        async def boom(**kwargs):
            raise AssertionError('loader must not run for non-trigger op')

        monkeypatch.setattr(TelegramNode, 'load_field_value', staticmethod(boom))
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='tg-tools', node_type='automation-telegram',
            operation='send_message_to_chat', config={},
        )
        assert updates is None

    @pytest.mark.asyncio
    async def test_provider_node_without_operation_skipped(self):
        from utils.webhook_manager import WebhookManager
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='tg-tools', node_type='automation-telegram',
            operation=None, config={},
        )
        assert updates is None

    @pytest.mark.asyncio
    async def test_generic_path_mints_row_once(self, monkeypatch):
        from utils.webhook_manager import WebhookManager

        async def fake_mint(**kwargs):
            return {'webhook_id': 'wh-1', 'webhook_url': 'https://wh-1.hooks.example.test',
                    'relay_connected': True, 'is_production': True}

        monkeypatch.setattr(WebhookManager, 'get_or_create_webhook', staticmethod(fake_mint))
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='hook', node_type='trigger-webhook', operation=None, config={},
        )
        assert updates['webhook_url'] == 'https://wh-1.hooks.example.test'

        # Already minted → generic path is a no-op.
        updates2 = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='hook', node_type='trigger-webhook', operation=None,
            config={'webhook_url': 'https://wh-1.hooks.example.test'},
        )
        assert updates2 is None

    @pytest.mark.asyncio
    async def test_none_values_and_unknown_shapes_never_clobber(self, monkeypatch):
        """A loader returning webhook_url=None (or an unrecognized shape) must
        not null an already-minted URL through the caller's config.update()."""
        from nodes.telegram_node import TelegramNode
        from utils.webhook_manager import WebhookManager

        async def none_url_loader(**kwargs):
            return {'values': {'webhook_url': None, 'telegram_registered': False}}

        monkeypatch.setattr(TelegramNode, 'load_field_value', staticmethod(none_url_loader))
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='telegram-trigger', node_type='automation-telegram',
            operation='receive_webhook_messages', config={},
        )
        assert 'webhook_url' not in updates
        assert updates['telegram_registered'] is False

        async def unknown_shape_loader(**kwargs):
            return {'webhook_url': 'https://x', 'webhook_id': 'y'}  # no values/value key

        monkeypatch.setattr(TelegramNode, 'load_field_value', staticmethod(unknown_shape_loader))
        updates2 = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='telegram-trigger', node_type='automation-telegram',
            operation='receive_webhook_messages', config={},
        )
        assert updates2 == {}

    @pytest.mark.asyncio
    async def test_hidden_loadvalue_field_covers_poll_and_cron(self, monkeypatch):
        """Gmail poll / trigger-cron mark webhook_url ui:hidden+ui:loadValue
        (no webhook widget) — their loaders register schedules and must be
        provisioned headlessly too."""
        from nodes.gmail_node import GmailNode
        from utils.webhook_manager import WebhookManager

        calls = {}

        async def fake_loader(**kwargs):
            calls.update(kwargs)
            return {'values': {'webhook_url': 'https://poll.hooks.example.test',
                               'schedule_id': 'sched-1'}}

        monkeypatch.setattr(GmailNode, 'load_field_value', staticmethod(fake_loader))
        updates = await WebhookManager.provision_node_webhook(
            object(),
            user_id='u1', workflow_id='f9c4dee2-971c-40af-af70-77cfb1cf75e2',
            node_id='gm', node_type='automation-gmail',
            operation='poll_for_new_emails', config={},
        )
        assert calls['field_name'] == 'webhook_url'
        assert updates['schedule_id'] == 'sched-1'


class TestBuilderProvisionsWebhooks:
    @staticmethod
    def _builder(graph_state):
        from coder.workflow.agentic.builder import AgenticBuilder
        b = object.__new__(AgenticBuilder)
        b.graph_state = graph_state
        b.platform_ops = object()
        b.user_id = 'u1'
        b.workflow_id = 'f9c4dee2-971c-40af-af70-77cfb1cf75e2'
        return b

    @pytest.mark.asyncio
    async def test_set_credentials_triggers_provisioning(self, monkeypatch):
        """The the-reproduced-run shape: telegram-trigger existed from a prior turn;
        gen 2 only attaches its credential — provisioning must still run so
        setWebhook happens without a UI click."""
        import utils.database_pool as dbp
        from utils.webhook_manager import WebhookManager

        state = GraphState()
        state.nodes['telegram-trigger'] = NodeState(
            id='telegram-trigger', type='automation-telegram', label='TG',
            goal='trigger', operation='receive_webhook_messages',
            config={'credentialIds': {'telegram_bot_token': 'cred-1'}},
        )
        b = self._builder(state)

        monkeypatch.setattr(dbp, 'get_native_pool', lambda: object())
        provisioned = []

        async def fake_provision(pool, **kwargs):
            provisioned.append(kwargs['node_id'])
            return {'webhook_url': 'https://wh.hooks.example.test', 'telegram_registered': True}

        monkeypatch.setattr(
            WebhookManager, 'provision_node_webhook', staticmethod(fake_provision),
        )

        ops = [XmlOp(tag='set_credentials',
                     attrs={'node': 'telegram-trigger', 'id': 'cred-1'}, body=None)]
        field_results: list = []
        events = [e async for e in b._provision_trigger_webhooks(ops, [], field_results)]

        assert provisioned == ['telegram-trigger']
        assert state.nodes['telegram-trigger'].config['webhook_url'] == 'https://wh.hooks.example.test'
        assert any('Webhook provisioned for telegram-trigger' in r for r in field_results)
        assert [e.type for e in events] == ['node_updated']

    @pytest.mark.asyncio
    async def test_new_node_provisioned_and_error_surfaced(self, monkeypatch):
        import utils.database_pool as dbp
        from utils.webhook_manager import WebhookManager

        state = GraphState()
        state.nodes['telegram-trigger'] = NodeState(
            id='telegram-trigger', type='automation-telegram', label='TG',
            goal='trigger', operation='receive_webhook_messages', config={},
        )
        b = self._builder(state)
        monkeypatch.setattr(dbp, 'get_native_pool', lambda: object())

        async def fake_provision(pool, **kwargs):
            return {'webhook_url': 'https://wh.hooks.example.test',
                    'telegram_registered': False,
                    'telegram_error': 'Bot token not configured'}

        monkeypatch.setattr(
            WebhookManager, 'provision_node_webhook', staticmethod(fake_provision),
        )
        field_results: list = []
        _ = [e async for e in b._provision_trigger_webhooks([], ['telegram-trigger'], field_results)]
        assert any('provider registration incomplete' in r for r in field_results)

    @pytest.mark.asyncio
    async def test_config_field_write_triggers_provisioning(self, monkeypatch):
        """The 2026-08-04 form-trigger shape: the node existed from a prior
        turn and a later turn fills a required field (form_id). Registration
        is gated on config validity, so THIS is the turn that can finally arm
        the schedule + baseline — a non-operation <field> write must
        re-provision."""
        import utils.database_pool as dbp
        from utils.webhook_manager import WebhookManager

        state = GraphState()
        state.nodes['form'] = NodeState(
            id='form', type='automation-google-forms', label='Form',
            goal='trigger', operation='on_form_response',
            config={'form_id': '1abc'},
        )
        b = self._builder(state)
        monkeypatch.setattr(dbp, 'get_native_pool', lambda: object())
        provisioned = []

        async def fake_provision(pool, **kwargs):
            provisioned.append(kwargs['node_id'])
            return {'webhook_url': 'https://wh.hooks.example.test', 'trigger_registered': True}

        monkeypatch.setattr(
            WebhookManager, 'provision_node_webhook', staticmethod(fake_provision),
        )
        ops = [XmlOp(tag='field',
                     attrs={'node': 'form', 'name': 'form_id'}, body='1abc')]
        _ = [e async for e in b._provision_trigger_webhooks(ops, [], [])]
        assert provisioned == ['form']

    @pytest.mark.asyncio
    async def test_skips_without_platform_ops(self):
        state = GraphState()
        b = self._builder(state)
        b.platform_ops = None
        out = [e async for e in b._provision_trigger_webhooks([], ['x'], [])]
        assert out == []


class TestBuilderOperationChangeSelfHeal:
    """<field name="operation"> away from a trigger op routes through the
    webhook choke point, same as the canvas and MCP paths."""

    @staticmethod
    def _builder(graph_state):
        from coder.workflow.agentic.builder import AgenticBuilder
        b = object.__new__(AgenticBuilder)
        b.graph_state = graph_state
        b.platform_ops = object()
        b.user_id = 'u1'
        b.workflow_id = 'f9c4dee2-971c-40af-af70-77cfb1cf75e2'
        return b

    @staticmethod
    def _telegram_state(operation, config=None):
        state = GraphState()
        state.nodes['tg'] = NodeState(
            id='tg', type='automation-telegram', label='TG', goal='trigger',
            operation=operation, config=dict(config or {}),
        )
        return state

    @pytest.mark.asyncio
    async def test_trigger_to_action_tears_down_and_strips(self, monkeypatch):
        import utils.database_pool as dbp
        from utils.webhook_manager import WebhookManager

        old_config = {'webhook_url': 'https://wh.hooks.example.test', 'webhook_id': 'wh-1'}
        state = self._telegram_state('send_message_to_chat', config=dict(old_config))
        b = self._builder(state)
        monkeypatch.setattr(dbp, 'get_native_pool', lambda: object())

        calls = {}

        async def fake_change(pool, node_type, workflow_id, node_id,
                              old_op, new_op, old_config=None, user_id=None,
                              org_id=None, nodes_override=None):
            calls.update(old_op=old_op, new_op=new_op, node_id=node_id,
                         old_config=old_config, user_id=user_id,
                         nodes_override=nodes_override)
            return True

        monkeypatch.setattr(
            WebhookManager, 'handle_operation_change', staticmethod(fake_change),
        )
        field_results: list = []
        await b._self_heal_operation_changes(
            {'tg': ('receive_webhook_messages', dict(old_config))}, field_results,
        )
        assert calls['old_op'] == 'receive_webhook_messages'
        assert calls['new_op'] == 'send_message_to_chat'
        assert calls['old_config'] == old_config
        # New op needs no webhook → mirrored registration fields stripped.
        assert 'webhook_url' not in state.nodes['tg'].config
        assert 'webhook_id' not in state.nodes['tg'].config
        assert any('Deregistered' in r for r in field_results)

    @pytest.mark.asyncio
    async def test_unchanged_operation_is_noop(self, monkeypatch):
        import utils.database_pool as dbp
        from utils.webhook_manager import WebhookManager

        state = self._telegram_state('receive_webhook_messages')
        b = self._builder(state)
        monkeypatch.setattr(dbp, 'get_native_pool', lambda: object())

        async def boom(*a, **k):
            raise AssertionError('choke point must not run when op unchanged')

        monkeypatch.setattr(
            WebhookManager, 'handle_operation_change', staticmethod(boom),
        )
        await b._self_heal_operation_changes(
            {'tg': ('receive_webhook_messages', {})}, [],
        )

    @pytest.mark.asyncio
    async def test_credential_swap_routes_choke_point(self, monkeypatch):
        import utils.database_pool as dbp
        from utils.webhook_manager import WebhookManager

        state = self._telegram_state(
            'receive_webhook_messages',
            config={'credentialIds': {'telegram_bot_token': 'new-cred'}},
        )
        b = self._builder(state)
        monkeypatch.setattr(dbp, 'get_native_pool', lambda: object())

        calls = {}

        async def fake_cred_change(pool, node_type, workflow_id, node_id,
                                   old_config, new_config, user_id, org_id=None):
            calls.update(old=old_config, new=new_config, node_id=node_id)
            return 1

        monkeypatch.setattr(
            WebhookManager, 'handle_credential_change', staticmethod(fake_cred_change),
        )
        await b._self_heal_credential_change(
            state.nodes['tg'], {'telegram_bot_token': 'old-cred'}, [],
        )
        assert calls['old'] == {'credentialIds': {'telegram_bot_token': 'old-cred'}}
        assert calls['new'] == {'credentialIds': {'telegram_bot_token': 'new-cred'}}


class TestProvisioningIsLazyWithoutPool:
    """Non-webhook candidates must never touch the DB pool: get_pool()
    fail-fast raises in pool-less contexts (CI without Postgres), and the old
    code only reached it after schema-filtering — regression for the
    TestProcessingOrder::test_add_node_before_add_edge CI failure."""

    @pytest.mark.asyncio
    async def test_mcp_add_of_non_webhook_nodes_skips_pool(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from mcp_server import NoClickMCPServer, _user_id_var
        from utils.database_pool import get_native_pool

        sio = MagicMock()
        with patch("mcp_server.DatabasePoolMixin.__init__", return_value=None):
            srv = NoClickMCPServer(sio)
        srv._emit_builder_event = AsyncMock()

        async def raising_get_pool():
            return get_native_pool()  # raises when uninitialized

        srv.get_pool = raising_get_pool
        workflow_data = {"nodes": [], "edges": []}
        srv._load_workflow = AsyncMock(return_value=(workflow_data, None))
        srv._save_workflow = AsyncMock(return_value=None)

        token = _user_id_var.set("test-user-123")
        try:
            result = await srv._process_update_workflow(
                workflow_id="wf-1",
                updates_xml=(
                    '<add_node type="automation-rss" name="a" />\n'
                    '<add_node type="automation-rss" name="b" />'
                ),
                include_operations=False,
                include_configs=False,
            )
        finally:
            _user_id_var.reset(token)
        assert "a" in result["alias_map"] and "b" in result["alias_map"]

    def test_webhook_field_pre_filter(self):
        from utils.webhook_manager import WebhookManager
        assert WebhookManager.node_webhook_field_for('automation-rss', None) is None
        assert WebhookManager.node_webhook_field_for(
            'automation-telegram', 'receive_webhook_messages',
        ) == 'webhook_url'
        assert WebhookManager.node_webhook_field_for(
            'automation-gmail', 'poll_for_new_emails',
        ) == 'webhook_url'
        assert WebhookManager.node_webhook_field_for('trigger-webhook', None) == 'webhook_url'


class TestMcpAgentCredentialAutoAttach:
    """MCP update_config parity: a harness hint with a sole matching
    credential auto-attaches (primary type preferred)."""

    class _FakeConn:
        def __init__(self, rows):
            self._rows = rows

        async def fetch(self, query, *args):
            return self._rows

    class _FakePool:
        def __init__(self, rows):
            self._conn = TestMcpAgentCredentialAutoAttach._FakeConn(rows)

        def acquire(self):
            conn = self._conn

            class _Ctx:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *a):
                    return False

            return _Ctx()

    def _server(self, rows, monkeypatch):
        import wss.handlers.workflow_handler as wh
        from mcp_server import NoClickMCPServer

        async def fake_org(conn, uid):
            return None

        monkeypatch.setattr(wh, 'get_user_org_context', fake_org)
        srv = object.__new__(NoClickMCPServer)
        pool = self._FakePool(rows)

        async def get_pool():
            return pool

        srv.get_pool = get_pool
        return srv

    _HINT = {
        'credential_type': 'agent_openrouter',
        'accepted_types': ['agent_openrouter', 'agent_api_key'],
        'label': 'Openrouter agent credential',
    }

    @pytest.mark.asyncio
    async def test_sole_primary_attaches(self, monkeypatch):
        srv = self._server(
            [{'id': 'cred-a', 'credential_type': 'agent_openrouter'}], monkeypatch,
        )
        config = {'model': 'openclaw'}
        attached = await srv._auto_attach_agent_credential('u1', config, self._HINT)
        assert attached == {'credential_type': 'agent_openrouter', 'id': 'cred-a'}
        assert config['credentialIds'] == {'agent_openrouter': 'cred-a'}

    @pytest.mark.asyncio
    async def test_primary_preferred_over_secondary(self, monkeypatch):
        srv = self._server([
            {'id': 'cred-a', 'credential_type': 'agent_openrouter'},
            {'id': 'cred-k', 'credential_type': 'agent_api_key'},
        ], monkeypatch)
        config = {'model': 'openclaw'}
        attached = await srv._auto_attach_agent_credential('u1', config, self._HINT)
        assert attached == {'credential_type': 'agent_openrouter', 'id': 'cred-a'}

    @pytest.mark.asyncio
    async def test_ambiguous_leaves_hint(self, monkeypatch):
        srv = self._server([
            {'id': 'c1', 'credential_type': 'agent_api_key'},
            {'id': 'c2', 'credential_type': 'agent_api_key'},
        ], monkeypatch)
        config = {'model': 'openclaw'}
        attached = await srv._auto_attach_agent_credential('u1', config, self._HINT)
        assert attached is None
        assert 'credentialIds' not in config


# ============================================================================
# 3. Trigger refs in an agent's message
# ============================================================================

class TestIsTriggerSource:
    def test_dedicated_trigger_nodes(self):
        assert is_trigger_source('trigger-webhook', None) is True
        assert is_trigger_source('trigger-cron', 'default') is True

    def test_integration_trigger_operation(self):
        assert is_trigger_source('automation-telegram', 'receive_webhook_messages') is True

    def test_integration_action_operation(self):
        assert is_trigger_source('automation-telegram', 'send_message_to_chat') is False
        assert is_trigger_source('automation-telegram', None) is False


class TestStripAgentTriggerMessageRefs:
    def test_pure_ref_replaced_with_standing_message(self):
        cfg = {'message': "{{ $('telegram-trigger').message }}"}
        stripped = strip_agent_trigger_message_refs(
            cfg, ['telegram-trigger'], standing_message='Reply helpfully.',
        )
        assert stripped == ['telegram-trigger']
        assert cfg['message'] == 'Reply helpfully.'

    def test_pure_ref_falls_back_to_default_without_goal(self):
        cfg = {'message': "{{ $('tg').message }}"}
        strip_agent_trigger_message_refs(cfg, ['tg'])
        assert cfg['message'] == DEFAULT_AGENT_STANDING_MESSAGE

    def test_mixed_text_keeps_surrounding_instructions(self):
        cfg = {'message': "Reply to this: {{ $('tg').message }} politely"}
        stripped = strip_agent_trigger_message_refs(cfg, ['tg'])
        assert stripped == ['tg']
        assert cfg['message'] == 'Reply to this: politely'

    def test_non_trigger_refs_untouched(self):
        msg = "Summarize {{ $('fetcher').rows }} for me"
        cfg = {'message': msg}
        assert strip_agent_trigger_message_refs(cfg, ['telegram-trigger']) == []
        assert cfg['message'] == msg

    def test_no_message_or_no_triggers_noop(self):
        cfg = {'system_prompt': 'x'}
        assert strip_agent_trigger_message_refs(cfg, ['tg']) == []
        cfg2 = {'message': "{{ $('tg').message }}"}
        assert strip_agent_trigger_message_refs(cfg2, []) == []
        assert cfg2['message'] == "{{ $('tg').message }}"

    def test_execute_field_ops_strips_and_reports(self):
        state = GraphState()
        state.nodes['tg'] = NodeState(
            id='tg', type='automation-telegram', label='TG', goal='trigger',
            operation='receive_webhook_messages',
        )
        state.nodes['agent1'] = NodeState(
            id='agent1', type='agent', label='Agent',
            goal='Reply helpfully to Telegram messages.', operation='default',
            config={'model': 'openclaw'}, parent_ids=['tg'],
        )
        results = execute_field_ops(
            [_field_op('agent1', 'message', "{{ $('tg').message }}")], state,
        )
        assert state.nodes['agent1'].config['message'] == (
            'Reply helpfully to Telegram messages.'
        )
        assert any('delivered to the agent automatically' in r for r in results)


# ============================================================================
# 5. Trigger-aware credential done-gate (2026-07-30 Reddit-tracker zombie:
#    builder told the user a credential-less workflow "won't run" while its
#    hourly cron stayed live and produced 30+ dead runs)
# ============================================================================

class TestGraphHasActiveTrigger:
    def test_dedicated_trigger_node_counts(self):
        from coder.workflow.agentic.commands import graph_has_active_trigger
        state = GraphState()
        state.nodes['cron'] = NodeState(
            id='cron', type='trigger-cron', label='Hourly', goal='',
            operation='default', config={}, parent_ids=[],
        )
        assert graph_has_active_trigger(state) is True

    def test_disabled_trigger_does_not_count(self):
        from coder.workflow.agentic.commands import graph_has_active_trigger
        state = GraphState()
        state.nodes['cron'] = NodeState(
            id='cron', type='trigger-cron', label='Hourly', goal='',
            operation='default', config={'disabled': True}, parent_ids=[],
        )
        assert graph_has_active_trigger(state) is False

    def test_plain_action_graph_has_no_trigger(self):
        from coder.workflow.agentic.commands import graph_has_active_trigger
        state = _agent_state()
        assert graph_has_active_trigger(state) is False
