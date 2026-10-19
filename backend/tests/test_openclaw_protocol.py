"""Public transcript receipts distinguish a steered alias from its owner run."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

import pytest
from nodes.agent.openclaw_protocol import BRIDGE_READY_S, DENIED_TOOLS, OpenClawReceipts, bridge_env

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
async def test_bridge_retries_startup_once_per_attempt_and_never_after_ready(scenario, tmp_path):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the gateway bridge')
    backend = Path(__file__).parents[1]
    proc = await asyncio.create_subprocess_exec(
        node, str(backend / 'tests/fixtures/openclaw_websocket_peer.mjs'),
        str(backend / 'nodes/agent/openclaw_bridge.mjs'),
        env={**os.environ, **bridge_env(), 'NOCLICK_WS_SCENARIO': scenario,
             'OPENCLAW_CONFIG_PATH': str(tmp_path / 'openclaw.json'),
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


_FAKE_OPENCLAW = '''#!{python}
import os, pathlib, sys, time
state = pathlib.Path(os.environ["FAKE_OPENCLAW_STATE"])
with (state / "calls").open("a") as log:
    log.write(" ".join(sys.argv[1:]) + " skip_cron=" + os.environ.get("OPENCLAW_SKIP_CRON", "") + "\\n")
if sys.argv[1] == "doctor":
    time.sleep(float(os.environ.get("FAKE_DOCTOR_SECONDS", "0")))
    if not os.environ.get("FAKE_DOCTOR_CANNOT_FIX"):
        (state / "migrated").touch()
    sys.exit(0)
if not (state / "migrated").exists():
    sys.stderr.write("Gateway failed to start: Legacy workspace setup state requires migration "
                     "for /workspace; run openclaw doctor --fix.\\n")
    sys.exit(1)
(state / "up").touch()
time.sleep(30)
'''


async def _bridge_over_fake_gateway(tmp_path, **extra_env):
    """The bridge driving a fake ``openclaw`` that refuses to start on state an
    older version wrote until ``doctor --fix`` has migrated it."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the gateway bridge')
    backend = Path(__file__).parents[1]
    binary = tmp_path / 'openclaw'
    binary.write_text(_FAKE_OPENCLAW.format(python=sys.executable))
    binary.chmod(0o755)
    proc = await asyncio.create_subprocess_exec(
        node, str(backend / 'tests/fixtures/openclaw_websocket_peer.mjs'),
        str(backend / 'nodes/agent/openclaw_bridge.mjs'),
        env={**os.environ, **bridge_env(), 'OPENCLAW_CONFIG_PATH': str(tmp_path / 'openclaw.json'), **extra_env,
             'NOCLICK_WS_SCENARIO': 'gateway', 'FAKE_OPENCLAW_STATE': str(tmp_path),
             'NOCLICK_TEST_GATEWAY_UP': str(tmp_path / 'up'),
             'NOCLICK_OPENCLAW_COMMAND': json.dumps([str(binary), 'gateway', '--port', '1']),
             'NOCLICK_OPENCLAW_URL': 'ws://127.0.0.1:1', 'OPENCLAW_GATEWAY_TOKEN': 'test-only'},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    return proc, lambda: (tmp_path / 'calls').read_text().splitlines()


async def test_bridge_migrates_state_from_an_older_openclaw_once_then_starts(tmp_path):
    """A conversation kept across an OpenClaw bump: its gateway refuses the old
    state and names `openclaw doctor --fix`. The bridge runs it once against the
    same state and starts again, and no OpenClaw automation runs in any of it
    (a gateway registers a heartbeat, a weekly review and a daily agent turn as
    it starts)."""
    proc, calls = await _bridge_over_fake_gateway(tmp_path)
    try:
        ready = json.loads(await asyncio.wait_for(proc.stdout.readline(), 15))
        assert ready['method'] == 'bridge/ready'
        assert calls() == ['gateway --port 1 skip_cron=1', 'doctor --fix --non-interactive skip_cron=1',
                           'gateway --port 1 skip_cron=1']
    finally:
        if proc.returncode is None:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 5)


async def test_bridge_starts_the_gateway_on_the_config_it_was_given(tmp_path):
    """OpenClaw's copies of an earlier config (its .bak ring and last-good) hold
    settings and tokens NoClick has since replaced, and a gateway restores .bak
    over a config that looks clobbered to it. None is left for it to restore."""
    config = tmp_path / 'openclaw.json'
    config.write_text('{"current": true}')
    for name in ('openclaw.json.bak', 'openclaw.json.bak.1', 'openclaw.json.bak.4', 'openclaw.json.last-good'):
        (tmp_path / name).write_text('{"stale": true}')
    (tmp_path / 'openclaw.json.clobbered.2026-10-17T02-30-06-748Z').write_text('{"kept": true}')
    (tmp_path / 'migrated').touch()
    proc, calls = await _bridge_over_fake_gateway(tmp_path)
    try:
        ready = json.loads(await asyncio.wait_for(proc.stdout.readline(), 15))
        assert ready['method'] == 'bridge/ready'
        assert sorted(p.name for p in tmp_path.glob('openclaw.json*')) == [
            'openclaw.json', 'openclaw.json.clobbered.2026-10-17T02-30-06-748Z']
        assert config.read_text() == '{"current": true}'
    finally:
        if proc.returncode is None:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 5)


async def test_bridge_repairs_at_most_once(tmp_path):
    proc, calls = await _bridge_over_fake_gateway(tmp_path, FAKE_DOCTOR_CANNOT_FIX='1')
    try:
        assert await asyncio.wait_for(proc.wait(), 15) == 1
        assert await proc.stdout.read() == b''
        assert [c.split()[0] for c in calls()] == ['gateway', 'doctor', 'gateway']
    finally:
        if proc.returncode is None:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 5)


async def test_bridge_gives_a_repair_its_own_time_then_a_fresh_start_window(tmp_path):
    """A large state migration outlasts the gateway's start window. The repair
    has a bound of its own, and the gateway gets a whole window again after it,
    or the repair is cut short on every cold start and never finishes. The clock
    here runs 100x: the 60s window passes during this 1.5s repair."""
    proc, calls = await _bridge_over_fake_gateway(tmp_path, NOCLICK_TEST_CLOCK_SCALE='100', FAKE_DOCTOR_SECONDS='1.5')
    try:
        ready = json.loads(await asyncio.wait_for(proc.stdout.readline(), 15))
        assert ready['method'] == 'bridge/ready'
        assert [c.split()[0] for c in calls()] == ['gateway', 'doctor', 'gateway']
    finally:
        if proc.returncode is None:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 5)


async def test_bridge_stops_a_repair_that_outlasts_its_bound(tmp_path):
    proc, calls = await _bridge_over_fake_gateway(tmp_path, NOCLICK_OPENCLAW_DOCTOR_MS='1000',
                                                  FAKE_DOCTOR_SECONDS='30')
    try:
        assert await asyncio.wait_for(proc.wait(), 15) == 1
        assert b'openclaw doctor --fix did not finish within 1s' in await proc.stderr.read()
        assert not (tmp_path / 'migrated').exists()  # the repair was stopped, not left running
        assert [c.split()[0] for c in calls()] == ['gateway', 'doctor']
    finally:
        if proc.returncode is None:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 5)


def test_the_local_session_waits_out_a_repair():
    """The open edition's session outwaits the bridge's worst case: a start
    the gateway refuses, the repair, and the start after it."""
    from nodes.agent.local_process import openclaw as local_openclaw

    env = bridge_env()
    assert BRIDGE_READY_S == (2 * int(env['NOCLICK_OPENCLAW_START_MS']) + int(env['NOCLICK_OPENCLAW_DOCTOR_MS'])) // 1000
    assert local_openclaw.GATEWAY_READY_S > BRIDGE_READY_S


@pytest.mark.parametrize('persistent', [True, False])
def test_the_local_edition_withholds_openclaws_scheduling_tool(tmp_path, monkeypatch, persistent):
    """No OpenClaw scheduler runs in a gateway NoClick owns (OPENCLAW_SKIP_CRON),
    so its cron tool would accept a reminder that never fires."""
    from types import SimpleNamespace

    from nodes.agent import local_harness

    monkeypatch.setattr(local_harness, '_require_binary', lambda name, hint: name)
    config = SimpleNamespace(openclaw_model='anthropic/claude-sonnet-4-5', message='hi', system_prompt='')
    local_harness._build_command('openclaw', config, tmp_path, None, persistent=persistent)
    written = json.loads((tmp_path / '.openclaw' / 'config.json').read_text())
    assert 'cron' in written['tools']['deny'] and DENIED_TOOLS == ('cron',)


async def test_bridge_gives_up_on_a_gateway_that_accepts_and_never_answers(tmp_path):
    """No error or close ever comes from a gateway that accepts the connection
    and goes silent, so the start window holds by the clock too, not only on a
    retry. The clock here runs 100x: the 60s window passes in about 0.6s."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the gateway bridge')
    backend = Path(__file__).parents[1]
    proc = await asyncio.create_subprocess_exec(
        node, str(backend / 'tests/fixtures/openclaw_websocket_peer.mjs'),
        str(backend / 'nodes/agent/openclaw_bridge.mjs'),
        env={**os.environ, **bridge_env(), 'NOCLICK_WS_SCENARIO': 'silent', 'NOCLICK_TEST_CLOCK_SCALE': '100',
             'OPENCLAW_CONFIG_PATH': str(tmp_path / 'openclaw.json'),
             'NOCLICK_OPENCLAW_COMMAND': json.dumps([sys.executable, '-c', 'import time; time.sleep(30)']),
             'NOCLICK_OPENCLAW_URL': 'ws://127.0.0.1:1', 'OPENCLAW_GATEWAY_TOKEN': 'test-only'},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert await asyncio.wait_for(proc.wait(), 10) == 1
        assert await proc.stdout.read() == b''
        assert b'OpenClaw gateway did not answer within 60s' in await proc.stderr.read()
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def test_a_local_gateway_that_could_not_start_shows_the_person_only_that(tmp_path):
    """The bridge's output (the gateway's, a state repair's) can quote the
    config it was given. The person reads that the gateway didn't start; the
    end of that output is diagnostics, for the log."""
    from nodes.agent.local_process.openclaw import OpenClawSession
    from nodes.core.base import FailureWithDiagnostics

    secret = 'Bearer sk-live-0123456789abcdef'
    script = f"import sys; sys.stderr.write('mcp.noclick: headers Authorization {secret} invalid\\\\n'); sys.exit(1)"
    session = OpenClawSession(workdir=tmp_path, env=dict(os.environ), command=[sys.executable, '-c', script],
                              cleanup=lambda: None)
    try:
        with pytest.raises(FailureWithDiagnostics) as raised:
            await asyncio.wait_for(session.start(), 10)
    finally:
        await session.close('test over')
    assert str(raised.value) == 'OpenClaw gateway could not start'
    assert secret in raised.value.diagnostics
