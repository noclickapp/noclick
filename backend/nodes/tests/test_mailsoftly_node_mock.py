"""Mailsoftly single-call transport and credential regression tests."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from pydantic import ValidationError
from nodes.mailsoftly_node import MailsoftlyNode, MailsoftlyAPIKeyCredential, MailsoftlyNodeConfig


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,payload', [
    ('get_contacts', {}, 'GET', {'page': 1, 'per_page': 50, 'order': 'oldest'}),
    ('create_contact', {'email': 'john@example.com'}, 'POST', {'email': 'john@example.com'}),
    ('update_contact', {'contact_id': 42, 'company': 'Acme'}, 'POST', {'contact_id': 42, 'company': 'Acme'}),
    ('assign_tag_to_contact', {'contact_id': 42, 'tag_name': 'VIP'}, 'POST', {'contact_id': 42, 'tag_name': 'VIP'}),
    ('add_global_email_unsubscriber', {'email': 'john@example.com'}, 'POST', {'email': 'john@example.com'}),
])
async def test_request(operation, config, method, payload):
    client = AsyncMock()
    body = {'status': 'success', 'contacts': [], 'has_more': True, 'page': 1}
    client.request.return_value = httpx.Response(200, json=body)
    @asynccontextmanager
    async def factory(**kwargs):
        yield client
    node = object.__new__(MailsoftlyNode)
    node._config = MailsoftlyNode.parse_config({'config': {'operation': operation, **config}, 'credentials': {'api_key': 'test-key-123'}})
    node.emit = AsyncMock()
    with patch('nodes.mailsoftly_node.guarded_async_client', factory):
        assert await node.execute({}) == body
    client.request.assert_awaited_once_with(method, 'https://app.mailsoftly.com/api/v3/' + operation,
        headers={'Authorization': 'test-key-123', 'Accept': 'application/json'},
        **({'params': payload} if method == 'GET' else {'json': payload}))


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'error': 'Rejected test-key-123'}), (200, {'status': 'error', 'error': 'Rejected test-key-123'})])
async def test_errors(status, body):
    client = AsyncMock()
    client.request.return_value = httpx.Response(status, json=body)
    @asynccontextmanager
    async def factory(**kwargs):
        yield client
    node = object.__new__(MailsoftlyNode)
    node._config = MailsoftlyNode.parse_config({'config': {'operation': 'get_account'}, 'credentials': {'api_key': 'test-key-123'}})
    node.emit = AsyncMock()
    with patch('nodes.mailsoftly_node.guarded_async_client', factory), pytest.raises(ValueError, match=r'Rejected \[redacted\]'):
        await node.execute({})
    node.emit.assert_not_awaited()


def test_manual_credential_default_and_required_inputs():
    assert MailsoftlyAPIKeyCredential(api_key='actual-key').credential_type == 'mailsoftly_api_key'
    for config in [{'operation': 'create_contact'}, {'operation': 'update_contact'}, {'operation': 'assign_tag_to_contact', 'contact_id': 42}]:
        with pytest.raises(ValidationError):
            MailsoftlyNodeConfig(config=config)
