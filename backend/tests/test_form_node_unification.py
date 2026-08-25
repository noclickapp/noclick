"""
Pins the 2026-07 form-node unification: the trigger-form-input node AND the
interface-config-form node merged into interface-form, which is now an
interface block, a public-link trigger, and a persistent value store in one.

Covers the seams the merges touched:
- registry alias resolution (saved graphs still carry the legacy type strings)
- the merged FormConfig (webhook link fields + form fields + values store)
- the merged execute (trigger-style output shapes + persisted-store output,
  both {{node.field}} and legacy {{node.values.field}} reference styles)
- the webhook route's form-node config reader accepting legacy type strings
"""

import pytest
from unittest.mock import AsyncMock

from nodes.core.registry import NODE_REGISTRY, LEGACY_NODE_TYPE_ALIASES, resolve_node_type
from nodes.interface.form_node import (
    FormConfig,
    FormField,
    FormInterfaceNode,
    FormInterfaceNodeConfig,
    parse_form_fields,
    persisted_form_values,
)


class TestRegistryAlias:
    @pytest.mark.parametrize('legacy', ['trigger-form-input', 'interface-config-form'])
    def test_legacy_type_resolves_to_form_interface_node(self, legacy):
        assert LEGACY_NODE_TYPE_ALIASES[legacy] == 'interface-form'
        assert NODE_REGISTRY.get(legacy) is FormInterfaceNode
        assert NODE_REGISTRY[legacy] is FormInterfaceNode
        assert legacy in NODE_REGISTRY

    @pytest.mark.parametrize('legacy', ['trigger-form-input', 'interface-config-form'])
    def test_legacy_type_not_iterated(self, legacy):
        """Schema generation / MCP listings walk items() and must not re-emit it."""
        assert legacy not in list(NODE_REGISTRY.keys())

    def test_resolve_node_type(self):
        assert resolve_node_type('trigger-form-input') == 'interface-form'
        assert resolve_node_type('interface-config-form') == 'interface-form'
        assert resolve_node_type('interface-form') == 'interface-form'
        assert resolve_node_type('automation-slack') == 'automation-slack'
        assert resolve_node_type(None) is None

    def test_is_trigger_source(self):
        from coder.workflow.workflow_ops import is_trigger_source
        assert is_trigger_source('interface-form', None) is True


class TestMergedConfig:
    def test_has_link_and_form_fields(self):
        fields = FormConfig.model_fields
        for name in ('webhook_id', 'webhook_url', 'title', 'description', 'fields'):
            assert name in fields, name

    def test_webhook_url_uses_webhook_widget(self):
        extra = FormConfig.model_fields['webhook_url'].json_schema_extra
        assert extra['ui:widget'] == 'webhook'
        assert extra['ui:copyable'] is True
        assert extra['ui:loadValue'] is True

    def test_fields_accept_json_string(self):
        cfg = FormConfig(fields='[{"name": "email", "type": "string"}]')
        assert [f.name for f in cfg.fields] == ['email']
        assert parse_form_fields('not json') == []


def _make_node(config_fields=None, node_data=None, values=None):
    config = None
    if config_fields is not None:
        config = FormInterfaceNodeConfig(config=FormConfig(fields=config_fields, values=values))
    node = FormInterfaceNode(
        node_id='form-1',
        node_type='interface-form',
        node_data=node_data or {},
        config=config,
        workflow_id='wf-1',
    )
    node.emit = AsyncMock()
    return node


class TestMergedExecute:
    @pytest.mark.asyncio
    async def test_schema_mode_without_inputs(self):
        node = _make_node(config_fields=[FormField(name='email')])
        result = await node.execute({})
        assert result['type'] == 'form_schema'
        assert result['status'] == 'schema'
        assert [f['name'] for f in result['fields']] == ['email']
        node.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_triggered_mode_flattens_inputs(self):
        node = _make_node(config_fields=[FormField(name='email')])
        result = await node.execute({'email': 'a@b.co'})
        assert result['type'] == 'form_triggered'
        assert result['email'] == 'a@b.co'

    @pytest.mark.asyncio
    async def test_sdk_config_override_fallback(self):
        """Values landed in node config (SDK config overrides) still trigger."""
        node = _make_node(
            config_fields=[FormField(name='domain')],
            node_data={'domain': 'noclick.com'},
        )
        result = await node.execute({})
        assert result['type'] == 'form_triggered'
        assert result['domain'] == 'noclick.com'
        assert result['values'] == {'domain': 'noclick.com'}


class TestPersistedValueStore:
    """The interface-config-form half: config.values + defaults on every run."""

    def test_persisted_form_values_merges_defaults(self):
        cfg = {'config': {
            'fields': [
                {'name': 'tz', 'default': 'UTC'},
                {'name': 'limit'},
                {'name': 'chan', 'default': 'general'},
            ],
            'values': {'limit': 5, 'chan': 'alerts', 'removed_field': 'x'},
        }}
        # Stored beats default; unset+no-default omitted; unknown names dropped
        assert persisted_form_values(cfg) == {'tz': 'UTC', 'limit': 5, 'chan': 'alerts'}

    def test_persisted_form_values_tolerates_json_strings_and_flat_shape(self):
        cfg = {'fields': '[{"name": "a"}]', 'values': '{"a": 1}'}
        assert persisted_form_values(cfg) == {'a': 1}

    @pytest.mark.asyncio
    async def test_plain_run_outputs_store_flat_and_nested(self):
        """Config-form behavior: no submission needed — every run feeds downstream,
        resolving both {{node.field}} and legacy {{node.values.field}}."""
        node = _make_node(
            config_fields=[FormField(name='tz', default='UTC'), FormField(name='limit')],
            node_data={'config': {
                'fields': [{'name': 'tz', 'default': 'UTC'}, {'name': 'limit'}],
                'values': {'limit': 5},
            }},
        )
        result = await node.execute({})
        assert result['tz'] == 'UTC'
        assert result['limit'] == 5
        assert result['values'] == {'tz': 'UTC', 'limit': 5}
        assert result['type'] == 'form_schema'

    @pytest.mark.asyncio
    async def test_submission_wins_over_store(self):
        node = _make_node(
            config_fields=[FormField(name='email')],
            node_data={'config': {
                'fields': [{'name': 'email'}],
                'values': {'email': 'stored@x.co'},
            }},
        )
        result = await node.execute({'email': 'submitted@x.co'})
        assert result['email'] == 'submitted@x.co'
        assert result['values'] == {'email': 'submitted@x.co'}
        assert result['type'] == 'form_triggered'

    def test_trigger_payload_folds_store_under_submission(self):
        config = {
            'fields': [{'name': 'tz', 'default': 'UTC'}, {'name': 'q'}],
            'values': {},
        }
        resolved = FormInterfaceNode.resolve_trigger_payload({'q': 'hello'}, config)
        assert resolved == {'tz': 'UTC', 'values': {'tz': 'UTC', 'q': 'hello'}, 'q': 'hello'}

    def test_trigger_payload_unchanged_without_store(self):
        """Pre-merge forms: the payload passes through byte-identical."""
        payload = {'q': 'hello'}
        assert FormInterfaceNode.resolve_trigger_payload(payload, {'fields': [{'name': 'q'}]}) is payload


class TestWebhookRouteFormReader:
    @pytest.mark.parametrize('node_type', ['interface-form', 'trigger-form-input', 'interface-config-form'])
    def test_get_form_node_config_accepts_both_types(self, node_type):
        from utils.webhook_routes import _get_form_node_config
        workflow_config = {
            'nodes': [{
                'id': 'form-1',
                'type': node_type,
                'config': {
                    'title': 'Intake',
                    'fields': '[{"name": "email"}]',
                },
            }]
        }
        cfg = _get_form_node_config(workflow_config, 'form-1')
        assert cfg is not None
        assert cfg['title'] == 'Intake'
        assert cfg['fields'] == [{'name': 'email'}]

    def test_get_form_node_config_rejects_other_types(self):
        from utils.webhook_routes import _get_form_node_config
        workflow_config = {
            'nodes': [{'id': 'n1', 'type': 'trigger-webhook', 'config': {}}]
        }
        assert _get_form_node_config(workflow_config, 'n1') is None
