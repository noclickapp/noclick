"""Public transcript receipts distinguish a steered alias from its owner run."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

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


@pytest.mark.parametrize('scenario', ['error', 'error-close', 'sidecars'])
async def test_bridge_retries_startup_once_per_attempt_and_never_after_ready(scenario):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the gateway bridge')
    backend = Path(__file__).parents[1]
    proc = await asyncio.create_subprocess_exec(
        node, str(backend / 'tests/fixtures/openclaw_websocket_peer.mjs'),
        str(backend / 'nodes/agent/openclaw_bridge.mjs'),
        env={**os.environ, 'NOCLICK_WS_SCENARIO': scenario,
             'NOCLICK_OPENCLAW_COMMAND': json.dumps([sys.executable, '-c', 'import time; time.sleep(30)']),
             'NOCLICK_OPENCLAW_URL': 'ws://127.0.0.1:1', 'OPENCLAW_GATEWAY_TOKEN': 'test-only'},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        ready = json.loads(await asyncio.wait_for(proc.stdout.readline(), 5))
        assert ready['method'] == 'bridge/ready'
        proc.stdin.write(b'{"id":1,"method":"probe","params":{}}\n')
        await proc.stdin.drain()
        result = json.loads(await asyncio.wait_for(proc.stdout.readline(), 5))
        assert result == {'id': 1, 'result': {'attempts': 2}}
        proc.stdin.write(b'{"id":2,"method":"disconnect","params":{}}\n')
        await proc.stdin.drain()
        assert await asyncio.wait_for(proc.wait(), 5) == 1
        assert await proc.stdout.read() == b''
    finally:
        if proc.returncode is None:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 5)
