"""Real installed CLIs against a local provider; no paid accounts or services.

Run explicitly with NOCLICK_TEST_LOCAL_CLIS=1. CI can install the pinned CLIs
and use this same test in the exported repository.
"""
import asyncio
import json
import os
import shutil
import socket
from types import SimpleNamespace

import pytest
import pytest_asyncio
import uvicorn

from tests.fixtures.local_model import LocalModel
from nodes.agent.local_harness import run_local_harness_turn, close_local_harness_sessions, router
from nodes.agent.local_process.session import sessions


@pytest_asyncio.fixture
async def native_environment(kind, binary, monkeypatch, tmp_path):
    assert shutil.which(binary), f'Install {binary} to run the native CLI suite'
    # No operator credentials, gateway integrations, or shell config in CLI tests.
    for name in list(os.environ):
        if name not in {'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT'}:
            monkeypatch.delenv(name)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('NOCLICK_LOCAL', '1')
    model = LocalModel(call_tool=True)
    async def not_rehearsing(*args):
        return False
    monkeypatch.setattr('nodes.agent.tool_execution.is_rehearsing', not_rehearsing)
    monkeypatch.setattr('utils.tool_call_log.record_tool_call', lambda **kw: None)
    monkeypatch.setattr('nodes.agent.local_harness._spawn_step', lambda *args: None)
    model.app.include_router(router)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    base = f'http://127.0.0.1:{sock.getsockname()[1]}'
    monkeypatch.setenv('NOCLICK_BACKEND_PORT', str(sock.getsockname()[1]))
    server = uvicorn.Server(uvicorn.Config(model.app, log_level='error'))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(.01)
    auth = tmp_path / 'cli'
    auth.mkdir()
    if kind == 'codex':
        (auth / 'config.toml').write_text(f'''model_provider = "localtest"
model = "gpt-5-codex"
[model_providers.localtest]
name = "localtest"
base_url = "{base}/v1"
wire_api = "responses"
env_key = "NOCLICK_TEST_KEY"
''')
        env = {'CODEX_HOME': str(auth), 'NOCLICK_TEST_KEY': 'fake-local-key'}
    elif kind == 'openclaw':
        env = {'ANTHROPIC_API_KEY': 'fake-local-key', 'ANTHROPIC_BASE_URL': base}
    elif kind == 'hermes_agent':
        env = {'ANTHROPIC_API_KEY': 'fake-local-key', 'ANTHROPIC_BASE_URL': base,
               'HERMES_INFERENCE_PROVIDER': 'anthropic', 'HERMES_INFERENCE_MODEL': 'claude-haiku-4-5'}
    elif kind == 'opencode':
        env = {'ANTHROPIC_API_KEY': 'fake-local-key', 'OPENCODE_DISABLE_MODELS_FETCH': 'true',
               'OPENCODE_CONFIG_CONTENT': json.dumps({
                   'provider': {'anthropic': {'options': {'baseURL': base + '/v1', 'apiKey': 'fake-local-key'}}},
                   'agent': {'title': {'disable': True}, 'summary': {'disable': True}},
               })}
    else:
        env = {'CLAUDE_CONFIG_DIR': str(auth), 'ANTHROPIC_BASE_URL': base,
               'ANTHROPIC_API_KEY': 'fake-local-key', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'}
    try:
        yield env, model, base, auth
    finally:
        model.release.set()
        await close_local_harness_sessions()
        server.should_exit = True
        await serving


@pytest.mark.skipif(os.environ.get('NOCLICK_TEST_LOCAL_CLIS') != '1', reason='requires installed CLI binaries')
@pytest.mark.parametrize('kind,binary', [('codex', 'codex'), ('claude_code', 'claude'), ('opencode', 'opencode'), ('hermes_agent', 'hermes'), ('openclaw', 'openclaw')])
@pytest.mark.asyncio
async def test_native_overlapping_inputs_are_consumed_and_session_becomes_idle(kind, binary, monkeypatch, tmp_path, native_environment):
    env, model, base, auth = native_environment
    saved = []
    async def persist(output, **kw):
        saved.append(output)
    node = SimpleNamespace(workflow_id='native', node_id='agent', conversation_id='native',
        chat_routing_id=lambda: 'native', _persist_llm_assistant_turn=persist, _execute_downstream_callback=model.echo)
    def submit(text):
        config = SimpleNamespace(conversation_key='same', message=text, system_prompt='',
                                 claude_code_model='claude-haiku-4-5', codex_model='gpt-5-codex', opencode_model='anthropic/claude-haiku-4-5', hermes_agent_model='anthropic/claude-haiku-4-5', openclaw_model='anthropic/claude-haiku-4-5')
        return asyncio.create_task(run_local_harness_turn(node, config, env, 'local-test', {'fixture_echo': {'tool_type': 'workflow', 'node_id': 'fixture', '_description': 'Echo a test input', '_parameters': {'type': 'object', 'properties': {}}}}, [], model_type=kind))
    tasks = []
    try:
        tasks.append(submit('NATIVE-ALPHA'))
        first_model = asyncio.create_task(model.started.wait())
        done, _ = await asyncio.wait([tasks[0], first_model], timeout=40, return_when=asyncio.FIRST_COMPLETED)
        if first_model not in done:
            first_model.cancel()
            assert False, json.dumps(tasks[0].result()) if tasks[0].done() else 'CLI did not call the local provider'

        tasks += [submit('NATIVE-BETA'), submit('NATIVE-GAMMA')]
        async with asyncio.timeout(10):
            while len(next(iter(sessions.entries.values()))[1].pending) < 3 or any(lock.locked() for lock in sessions.locks.values()):
                await asyncio.sleep(.01)
        model.release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 40)
        assert all(r['status'] == 'completed' for r in results), results
        assert len(sessions.entries) == 1
        assert not next(iter(sessions.entries.values()))[1].pending
        assert len(model.requests) >= 2
        assert model.tool_calls == [('fixture', {}, 'agent')]
        assert 'native-tool-result' in json.dumps(model.requests[1:])
        assert 'fixture_echo' in json.dumps(model.requests[0].get('tools', [])), model.requests[0].get('tools')
        assert 'NATIVE-BETA' not in json.dumps(model.requests[0])
        assert all(marker in json.dumps(model.requests[1:]) for marker in ['NATIVE-BETA', 'NATIVE-GAMMA'])
        if kind == 'hermes_agent':
            assert 1 <= len(saved) <= 3
        elif kind == 'claude_code':
            # A tool boundary can consume the queued inputs in this turn.
            assert 1 <= len(saved) <= 2
        else:
            assert len(saved) == 1
        assert len(saved) == sum(not result.get('skipped') for result in results)
        if kind == 'codex':
            from nodes.agent.cli_protocol import RpcError, steer_turn_ended
            current = next(iter(sessions.entries.values()))[1]
            with pytest.raises(RpcError) as rejected:
                await current.request('turn/steer', {'threadId': current.thread,
                    'expectedTurnId': 'already-ended', 'input': [{'type': 'text', 'text': 'must be rejected'}]})
            assert steer_turn_ended(rejected.value), str(rejected.value)
        before = len(model.requests)
        await close_local_harness_sessions()
        tasks.append(submit('NATIVE-DELTA'))
        resumed = await asyncio.wait_for(tasks[-1], 60)
        assert resumed['status'] == 'completed', resumed
        assert 'NATIVE-ALPHA' in json.dumps(model.requests[before:]), 'conversation history was lost on restart'
    finally:
        model.release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_local_harness_sessions()
