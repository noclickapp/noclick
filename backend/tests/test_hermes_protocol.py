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
    def request(self, method, path, body=None, **kw):
        self.calls.append((method, path, body))
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
