"""Open-edition regressions: real subprocesses, independent conversation keys.

The peer implements public wire formats only. These tests ship and run without
hosted packages, network credentials, or provider charges.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

import nodes.agent.local_harness as lh
from nodes.agent.local_process.session import sessions

PEER = Path(__file__).parent / 'fixtures' / 'local_cli_peer.py'


def config(message, key='same', **kw):
    return SimpleNamespace(message=message, conversation_key=key, system_prompt='',
                           codex_model='test', claude_code_model='test', **kw)


def node(persisted, *, workflow='workflow', agent='agent'):
    async def persist(output, **kw):
        persisted.append(output)
    return SimpleNamespace(workflow_id=workflow, node_id=agent, conversation_id='conversation',
                           chat_routing_id=lambda: 'conversation', _persist_llm_assistant_turn=persist)


def wire(directory):
    path = directory / '.wire'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.01)


@pytest_asyncio.fixture(autouse=True)
async def local_runtime(monkeypatch, tmp_path):
    await sessions.close()
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(lh, '_presence_hub', lambda: None)
    async def status(*a):
        pass
    monkeypatch.setattr(lh, '_emit_status', status)
    monkeypatch.setattr(lh, '_build_command', lambda kind, *a, **kw: ([sys.executable, str(PEER), kind], kind))
    yield
    await sessions.close()
    assert not lh._sessions


def directory(key='same', workflow='workflow', agent='agent'):
    return lh._workspace_dir(workflow, agent, key)


def run(n, cfg, kind='codex'):
    return asyncio.create_task(lh.run_local_harness_turn(n, cfg, {}, 'user', {}, [], model_type=kind))


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['codex', 'claude_code'])
async def test_same_key_delivers_during_active_model_call_without_second_process(kind):
    saved = []
    a = run(node(saved), config('ALPHA'), kind)
    workdir = directory()
    await until(lambda: any('model' in e for e in wire(workdir)))
    b, c = run(node(saved), config('BETA'), kind), run(node(saved), config('GAMMA'), kind)
    await until(lambda: sum(e.get('method') == 'turn/steer' or e.get('type') == 'user' for e in wire(workdir)) >= (2 if kind == 'codex' else 3))
    events = wire(workdir)
    assert len({e['pid'] for e in events}) == 1
    assert not a.done() and not b.done() and not c.done()
    (workdir / 'release-1').touch()
    (workdir / 'release-2').touch()
    results = await asyncio.wait_for(asyncio.gather(a, b, c), 5)
    if kind == 'codex':
        assert len(saved) == 1
        assert saved[0]['response'] == 'ALPHA|BETA|GAMMA'
        assert sum(bool(r.get('skipped')) for r in results) == 2
    else:
        assert len(saved) == 2
        assert saved[0]['response'] == 'ALPHA'
        assert saved[1]['response'] == 'BETA|GAMMA'
        assert sum(bool(r.get('skipped')) for r in results) == 1
    assert not next(iter(sessions.entries.values()))[1].pending


@pytest.mark.asyncio
@pytest.mark.parametrize('difference', ['key', 'node', 'workflow'])
async def test_independent_conversations_run_in_parallel(difference):
    saved = []
    first = run(node(saved), config('A'))
    other_node = node(saved, agent='other' if difference == 'node' else 'agent',
                      workflow='other' if difference == 'workflow' else 'workflow')
    other_key = 'other' if difference == 'key' else 'same'
    second = run(other_node, config('B', other_key))
    dirs = [directory(), directory(other_key, other_node.workflow_id, other_node.node_id)]
    await until(lambda: all(any('model' in e for e in wire(d)) for d in dirs))
    assert len({e['pid'] for d in dirs for e in wire(d)}) == 2
    for d in dirs:
        (d / 'release-1').touch()
    assert all(r['status'] == 'completed' for r in await asyncio.gather(first, second))


@pytest.mark.asyncio
async def test_next_turn_reuses_process_and_restart_resumes_thread():
    saved = []
    first = run(node(saved), config('A'))
    d = directory()
    await until(lambda: any('model' in e for e in wire(d)))
    (d / 'release-1').touch()
    await first
    second = run(node(saved), config('B'))
    await until(lambda: sum('model' in e for e in wire(d)) == 2)
    (d / 'release-2').touch()
    await second
    assert len({e['pid'] for e in wire(d)}) == 1
    await sessions.close()
    third = run(node(saved), config('C'))
    await third
    assert any(e.get('method') == 'thread/resume' for e in wire(d))
    assert len({e['pid'] for e in wire(d)}) == 2


@pytest.mark.asyncio
async def test_cancellation_stops_unowned_process_and_removes_session():
    task = run(node([]), config('A'))
    await until(lambda: any('model' in e for e in wire(directory())))
    session = next(iter(sessions.entries.values()))[1]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.proc.returncode is not None
    assert not sessions.entries


@pytest.mark.asyncio
async def test_dead_process_fails_every_pending_input():
    a = run(node([]), config('A'))
    await until(lambda: any('model' in e for e in wire(directory())))
    b = run(node([]), config('B'))
    await until(lambda: any(e.get('method') == 'turn/steer' for e in wire(directory())))
    session = next(iter(sessions.entries.values()))[1]
    session.proc.kill()
    results = await asyncio.wait_for(asyncio.gather(a, b), 5)
    assert all(r['status'] == 'failed' and r['error'] for r in results)
    assert not sessions.entries


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('system_prompt', 'changed instructions'), ('codex_model', 'changed model')])
async def test_configuration_change_waits_for_previous_process_to_finish(field, value):
    saved = []
    a = run(node(saved), config('A'))
    d = directory()
    await until(lambda: any('model' in e for e in wire(d)))
    original = next(iter(sessions.entries.values()))[1]
    changed = config('B')
    setattr(changed, field, value)
    b = run(node(saved), changed)
    await asyncio.sleep(.05)
    assert len({e['pid'] for e in wire(d)}) == 1
    assert not b.done()
    (d / 'release-1').touch()
    assert (await a)['status'] == 'completed'
    assert (await asyncio.wait_for(b, 5))['status'] == 'completed'
    assert original.proc.returncode is not None
    assert len({e['pid'] for e in wire(d)}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('key', [None, ''])
async def test_missing_key_creates_independent_conversations(key):
    a, b = run(node([]), config('A', key)), run(node([]), config('B', key))
    await until(lambda: len(sessions.entries) == 2 and all(s.proc for _, s in sessions.entries.values()))
    running = [s for _, s in sessions.entries.values()]
    assert len({s.workdir for s in running}) == 2
    assert len({s.proc.pid for s in running}) == 2
    for s in running:
        (s.workdir / 'release-1').touch()
    assert all(r['status'] == 'completed' for r in await asyncio.gather(a, b))


@pytest.mark.asyncio
async def test_cancelled_owner_does_not_cancel_other_accepted_input():
    saved = []
    a = run(node(saved), config('A'))
    await until(lambda: any('model' in e for e in wire(directory())))
    b = run(node(saved), config('B'))
    await until(lambda: any(e.get('method') == 'turn/steer' for e in wire(directory())))
    session = next(iter(sessions.entries.values()))[1]
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    assert session.proc.returncode is None
    (directory() / 'release-1').touch()
    result = await asyncio.wait_for(b, 5)
    assert not result.get('skipped') and result['response'] == 'A|B'
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_timeout_reaps_process_and_fails_input(monkeypatch):
    monkeypatch.setattr(lh, 'TURN_TIMEOUT_S', .4)
    task = run(node([]), config('A'))
    await until(lambda: any('model' in e for e in wire(directory())))
    session = next(iter(sessions.entries.values()))[1]
    result = await task
    assert result['status'] == 'failed' and 'timed out' in result['error']
    assert session.proc.returncode is not None
    assert not sessions.entries


@pytest.mark.asyncio
async def test_idle_process_expires_and_removes_tool_access(monkeypatch):
    from nodes.agent.local_process import session as module
    monkeypatch.setattr(module, 'IDLE_TIMEOUT_S', .05)
    n = node([])
    a = asyncio.create_task(lh.run_local_harness_turn(n, config('A'), {}, 'user',
        {'echo': {'_parameters': {'type': 'object'}}}, [], model_type='codex'))
    await until(lambda: any('model' in e for e in wire(directory())))
    session = next(iter(sessions.entries.values()))[1]
    assert lh._sessions
    (directory() / 'release-1').touch()
    await a
    await until(lambda: not sessions.entries)
    assert not lh._sessions and session.proc.returncode is not None


@pytest.mark.asyncio
async def test_tools_follow_next_claude_input_after_first_response(monkeypatch):
    import httpx
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(lh.router)
    seen = []
    async def execute(n, name, args, configs):
        seen.append(n)
        return {'owner': n.execution_id}
    monkeypatch.setattr('nodes.agent.tool_execution.execute_tool', execute)
    monkeypatch.setattr('utils.tool_call_log.record_tool_call', lambda **kw: None)
    monkeypatch.setattr(lh, '_spawn_step', lambda *args: None)
    saved = []
    first, second = node(saved), node(saved)
    first.execution_id, second.execution_id = 'first', 'second'
    tools = {'echo': {'_description': 'echo', '_parameters': {'type': 'object'}}}
    def submit(n, text):
        return asyncio.create_task(lh.run_local_harness_turn(n, config(text), {}, 'user', tools, [], model_type='claude_code'))
    a = submit(first, 'A')
    await until(lambda: any('model' in e for e in wire(directory())))
    b = submit(second, 'B')
    await until(lambda: sum(e.get('type') == 'user' for e in wire(directory())) == 2)
    token = next(iter(lh._sessions))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
        async def call():
            r = await client.post(f'/local-agent-mcp/{token}', json={'id': 1, 'method': 'tools/call', 'params': {'name': 'echo'}})
            assert not r.json()['result']['isError']
        await call()
        (directory() / 'release-1').touch()
        await a
        await until(lambda: sum('model' in e for e in wire(directory())) == 2)
        await call()
        assert seen == [first, second]
    (directory() / 'release-2').touch()
    await b


@pytest.mark.asyncio
async def test_startup_cancellation_removes_process_and_tool_access(monkeypatch):
    from nodes.agent.local_process.native import CodexSession
    from nodes.agent.local_process.session import Session
    started = asyncio.Event()
    async def stalled_start(self):
        await Session.start(self)
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(CodexSession, 'start', stalled_start)
    task = asyncio.create_task(lh.run_local_harness_turn(node([]), config('A'), {}, 'user',
        {'echo': {'_parameters': {'type': 'object'}}}, [], model_type='codex'))
    await asyncio.wait_for(started.wait(), 5)
    session = next(iter(sessions.entries.values()))[1]
    assert lh._sessions
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.stopped.is_set() and session.proc.returncode is not None
    assert not lh._sessions and not sessions.entries


@pytest.mark.asyncio
async def test_repeated_close_waits_for_cleanup_after_caller_cancellation(tmp_path):
    from nodes.agent.local_process.session import Session
    cleanup = []
    session = Session(workdir=tmp_path, env={}, command=[], cleanup=lambda: cleanup.append(True))
    ready, release = asyncio.Event(), asyncio.Event()
    async def child():
        try:
            ready.set()
            await asyncio.Event().wait()
        finally:
            await release.wait()
    session.task(child())
    await ready.wait()
    first = asyncio.create_task(session.close())
    await until(lambda: session.closed)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(session.close())
    await asyncio.sleep(.01)
    assert not second.done() and not session.stopped.is_set()
    release.set()
    await asyncio.wait_for(second, 5)
    assert session.stopped.is_set() and cleanup == [True]


@pytest.mark.asyncio
async def test_close_terminates_tool_child_after_cli_parent_exits(tmp_path):
    import os
    import psutil
    from nodes.agent.local_process.session import Session
    if os.name != 'posix':
        pytest.skip('POSIX process groups')
    child_pid = tmp_path / 'child.pid'
    script = ("import subprocess,sys; from pathlib import Path; "
              "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
              "Path('child.pid').write_text(str(p.pid))")
    session = Session(workdir=tmp_path, env=dict(os.environ),
        command=[sys.executable, '-c', script], cleanup=lambda: None)
    try:
        await session.start()
        await until(lambda: session.proc.returncode is not None)
        assert child_pid.exists()
        child = psutil.Process(int(child_pid.read_text()))
        assert child.is_running()
        await session.close()
        def dead():
            try:
                return not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                return True
        await until(dead)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_group_signal_denial_falls_back_to_owned_child(monkeypatch):
    import os
    if os.name != 'posix':
        pytest.skip('POSIX process groups')
    task = run(node([]), config('A'))
    await until(lambda: any('model' in e for e in wire(directory())))
    session = next(iter(sessions.entries.values()))[1]
    def denied(*args):
        raise PermissionError('group signal unavailable')
    monkeypatch.setattr('nodes.agent.local_process.session.os.killpg', denied)
    await session.close()
    assert session.proc.returncode is not None and session.stopped.is_set()
    assert (await task)['status'] == 'failed'
    assert not sessions.entries
