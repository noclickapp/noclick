"""Public Hermes Runs API: exact receipts and safe late-input handoff."""
import io
import json
import urllib.error

import pytest

from nodes.agent.hermes_protocol import HermesClient


class Peer(HermesClient):
    def __init__(self):
        super().__init__('http://127.0.0.1', 'test', 'session')
        self.calls = []
        self.state = {'status': 'running'}
        self.rejection = None
        self.run_number = 0
        # The session as the gateway keeps it (v2026.9.24): ``latest`` pages back from the newest, each page oldest
        # first.
        self.messages = []
    def request(self, method, path, body=None, **kw):
        self.calls.append((method, path, body))
        if path.startswith('/api/sessions/session/messages?'):
            query = dict(part.split('=') for part in path.split('?', 1)[1].split('&'))
            assert query['order'] == 'latest'
            limit, offset = int(query['limit']), int(query['offset'])
            newest_first = list(reversed(self.messages))[offset:offset + limit]
            return {'object': 'list', 'data': list(reversed(newest_first))}
        if path == '/v1/runs':
            self.run_number += 1
            self.state = {'status': 'running'}
            return {'run_id': f'run-{self.run_number}'}
        if path.endswith('/steer'):
            if self.rejection:
                raise self.rejection
            return {'accepted': True}
        return self.state


def test_late_steer_is_handed_off_without_repeating_consumed_input():
    client = Peer()
    a, b, c = [client.send(text) for text in ['A', 'B', 'C']]
    client.state = {'status': 'completed', 'output': 'first',
                    'pending_steer': [client.marked(b, 'B'), client.marked(c, 'C')]}
    first = client.poll_response()
    assert first['response'] == 'first' and first['input_ids'] == [a]
    starts = [body for method, path, body in client.calls if path == '/v1/runs']
    assert len(starts) == 2
    assert a not in starts[1]['input']
    assert b in starts[1]['input'] and c in starts[1]['input']
    client.state = {'status': 'completed', 'output': 'second'}
    assert client.poll_response()['input_ids'] == [b, c]
    assert not client.is_busy()


def test_definite_not_running_rejection_waits_then_steers():
    client = Peer()
    a = client.send('A')
    client.state = {'status': 'queued'}
    client.rejection = urllib.error.HTTPError('http://test', 409, '', {},
        io.BytesIO(json.dumps({'error': {'code': 'run_not_accepting_steer'}}).encode()))
    b = client.send('B')
    assert b in client.backlog and b not in client.inputs
    client.rejection = None
    client.state = {'status': 'running'}
    assert client.poll_response() is None
    assert b in client.inputs and not client.backlog
    client.state = {'status': 'completed', 'output': 'all'}
    assert client.poll_response()['input_ids'] == [a, b]


def test_uncertain_steer_is_not_queued_or_replayed():
    client = Peer()
    a = client.send('A')
    client.rejection = TimeoutError('accepted but acknowledgement lost')
    with pytest.raises(TimeoutError):
        client.send('B')
    assert not client.backlog
    assert client.run_number == 1
    assert list(client.inputs) == [a]


def test_failure_is_preserved_with_partial_output():
    client = Peer()
    a = client.send('A')
    client.state = {'status': 'failed', 'output': 'partial', 'error': 'provider failed'}
    assert client.poll_response() == {'response': 'partial', 'error': 'provider failed',
                                     'input_ids': [a], 'usage': {}}


def test_failed_deferred_start_preserves_prior_success_and_never_replays():
    client = Peer()
    a, b = client.send('A'), client.send('B')
    client.state = {'status': 'completed', 'output': 'first', 'pending_steer': [client.marked(b, 'B')]}
    request = client.request
    def uncertain(method, path, body=None, **kw):
        if path == '/v1/runs':
            raise TimeoutError('acknowledgement lost')
        return request(method, path, body, **kw)
    client.request = uncertain
    assert client.poll_response()['input_ids'] == [a]
    failure = client.poll_response()
    assert failure['input_ids'] == [b] and 'acknowledgement lost' in failure['error']
    assert client.poll_response() is None
    assert not client.is_busy()
    with pytest.raises(RuntimeError):
        client.send('C')


def test_only_native_activity_extends_busy_liveness(monkeypatch):
    now = [100]
    monkeypatch.setattr('nodes.agent.hermes_protocol.time.time', lambda: now[0])
    client = Peer()
    client.send('A')
    client.state = {'status': 'running', 'updated_at': 'first signal'}
    assert client.poll_response() is None
    now[0] = 200
    assert client.poll_response() is None
    assert client.last_activity == 100
    client.state['updated_at'] = 'tool completed'
    assert client.poll_response() is None
    assert client.last_activity == 200


def test_interrupted_run_finishes_receipts_and_preserves_partial_output():
    client = Peer()
    receipt = client.send('A')
    client.state = {'status': 'interrupted', 'output': 'partial'}
    response = client.poll_response()
    assert response['input_ids'] == [receipt]
    assert response['response'] == 'partial'
    assert response['error'] == 'Hermes run interrupted'
    assert not client.is_busy()


def _call(cid):
    return {'id': cid, 'type': 'function', 'function': {'name': 'terminal', 'arguments': '{"command": "hostname"}'}}


def test_a_runs_reply_is_every_message_it_wrote_a_paragraph_apart():
    # Hermes's ``output`` is the run's last message alone: the answer it wrote beside its tool calls reached no one.
    client = Peer()
    client.messages = [{'id': 1, 'role': 'user', 'content': '[noclick-input:old]\nRemember TANGERINE.'},
                       {'id': 2, 'role': 'assistant', 'content': 'Noted.'}]
    a = client.send('What code word did I ask you to remember? Then run hostname.')
    asked = client.calls[-1][2]['input']
    client.messages += [
        {'id': 3, 'role': 'user', 'content': asked},
        {'id': 4, 'role': 'assistant', 'content': 'The code word is **TANGERINE**.\n\nNow let me run it:',
         'tool_calls': [_call('c1')]},
        {'id': 5, 'role': 'tool', 'tool_call_id': 'c1', 'content': '{"output": "box", "exit_code": 0}'},
        {'id': 6, 'role': 'assistant', 'content': '', 'tool_calls': [_call('c2')]},
        {'id': 7, 'role': 'tool', 'tool_call_id': 'c2', 'content': '{"output": "box", "exit_code": 0}'},
        {'id': 8, 'role': 'assistant', 'content': 'hostname printed `box`.'}]
    client.state = {'status': 'completed', 'output': 'hostname printed `box`.'}
    response = client.poll_response()
    assert response['response'] == ('The code word is **TANGERINE**.\n\nNow let me run it:\n\n'
                                     'hostname printed `box`.')
    assert response['input_ids'] == [a]


def test_a_long_run_is_read_back_to_its_first_input_across_pages():
    client = Peer()
    a = client.send('Work through the list.')
    asked = client.calls[-1][2]['input']
    b = client.send('Also the second one.')  # steered into the run: still this run's
    client.messages = [{'id': 1, 'role': 'user', 'content': asked},
                       {'id': 2, 'role': 'assistant', 'content': 'Starting.'}]
    for n in range(3, 3 + 2 * 300, 2):
        client.messages += [{'id': n, 'role': 'assistant', 'content': '', 'tool_calls': [_call(f'c{n}')]},
                            {'id': n + 1, 'role': 'tool', 'tool_call_id': f'c{n}', 'content': '{}'}]
    client.messages += [{'id': 900, 'role': 'user', 'content': client.marked(b, 'Also the second one.')},
                        {'id': 901, 'role': 'assistant', 'content': 'Both done.'}]
    client.state = {'status': 'completed', 'output': 'Both done.'}
    response = client.poll_response()
    assert response['response'] == 'Starting.\n\nBoth done.' and response['input_ids'] == [a, b]


def test_a_session_that_cant_be_read_keeps_the_runs_own_output():
    client = Peer()
    a = client.send('A')
    request = client.request
    def unreadable(method, path, body=None, **kw):
        if path.startswith('/api/sessions/'):
            raise urllib.error.URLError('gateway busy')
        return request(method, path, body, **kw)
    client.request = unreadable
    client.state = {'status': 'completed', 'output': 'the last message'}
    assert client.poll_response() == {'response': 'the last message', 'error': None, 'input_ids': [a], 'usage': {}}
