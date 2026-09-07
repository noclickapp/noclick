"""Public transcript receipts distinguish a steered alias from its owner run."""
import pytest
from nodes.agent.openclaw_protocol import OpenClawReceipts

KEY = 'agent:main:test'


def event(ledger, name, **payload):
    return ledger.observe(name, {'sessionKey': KEY, **payload})


def target(ledger, receipt, owner):
    event(ledger, 'session.message', message={'role': 'user', '__openclaw': {
        'idempotencyKey': receipt + ':user', 'steerTargetRunId': owner}})


def test_alias_completions_do_not_complete_steered_inputs_or_emit_duplicate_results():
    ledger = OpenClawReceipts(KEY)
    for rid in ('A', 'B', 'C'):
        ledger.add(rid)
    target(ledger, 'B', 'A')
    target(ledger, 'C', 'A')
    # An acknowledgement may arrive after the authoritative transcript update.
    ledger.accepted('B', {'runId': 'B'})
    assert event(ledger, 'chat', runId='B', state='final') is None
    assert event(ledger, 'chat', runId='C', state='final') is None
    ledger.add('D')
    result = event(ledger, 'chat', runId='A', state='final', message={'content': [{'type': 'text', 'text': 'combined'}]})
    assert result == {'response': 'combined', 'error': None, 'input_ids': ['A', 'B', 'C']}
    assert list(ledger.pending) == ['D']
    assert event(ledger, 'chat', runId='A', state='final') is None
    assert event(ledger, 'chat', runId='D', state='final')['input_ids'] == ['D']
    assert not ledger.pending


@pytest.mark.parametrize('state', ['error', 'aborted'])
def test_failure_preserves_partial_response(state):
    ledger = OpenClawReceipts(KEY)
    ledger.add('A')
    result = event(ledger, 'chat', runId='A', state=state, errorMessage='failed', message={'content': 'partial'})
    assert result == {'response': 'partial', 'error': 'failed', 'input_ids': ['A']}


def test_other_conversation_events_cannot_complete_input():
    ledger = OpenClawReceipts(KEY)
    ledger.add('A')
    assert ledger.observe('chat', {'sessionKey': 'other', 'runId': 'A', 'state': 'final'}) is None
    assert list(ledger.pending) == ['A']
