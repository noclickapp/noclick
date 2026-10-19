"""The local edition's OpenCode session answers each input with OpenCode's own error: inputs that overlap a run
that failed (a key the provider rejects) fail with that run's words, whichever reply lands first, and an HTTP error
says what OpenCode said rather than a status line."""
import asyncio

import httpx
import pytest

from nodes.agent.local_process.native import OpenCodeSession

pytestmark = pytest.mark.asyncio

FAILED = {'name': 'APIError', 'data': {'message': 'Upstream request failed: Invalid credential'}}


def session(tmp_path, handler) -> OpenCodeSession:
    s = OpenCodeSession(model='opencode/model', base_url='http://opencode', password='p', workdir=tmp_path, env={},
                        command=[], cleanup=lambda: None)
    s.http = httpx.AsyncClient(base_url='http://opencode', transport=httpx.MockTransport(handler))
    s.session_id = 'session'
    return s


def waiting(s: OpenCodeSession, receipt: str) -> tuple[str, asyncio.Future]:
    mid = 'msg_' + receipt
    s.message_ids[mid] = receipt
    s.pending[receipt] = asyncio.get_running_loop().create_future()
    s.activations[receipt] = lambda _s: None
    return mid, s.pending[receipt]


async def _close(s):
    for task in list(s.tasks):
        task.cancel()
    await s.http.aclose()


@pytest.mark.parametrize('order', [('A', 'B'), ('B', 'A')])
async def test_inputs_overlapping_a_failed_run_fail_with_its_words(tmp_path, order):
    replies = {}

    def handler(request):
        return httpx.Response(200, json=replies['reply'])

    s = session(tmp_path, handler)
    mid_a, a = waiting(s, 'A')
    mid_b, b = waiting(s, 'B')
    # The run started from A failed; OpenCode answers every request waiting on it with that failed reply.
    replies['reply'] = {'info': {'id': 'failed', 'role': 'assistant', 'parentID': mid_a, 'error': FAILED}, 'parts': []}
    mids = {'A': mid_a, 'B': mid_b}
    for receipt in order:
        await s._message(receipt, 'hi', mids[receipt])
    assert a.result()['error'] == b.result()['error'] == 'Upstream request failed: Invalid credential'
    assert not s.pending and not s.closed
    await _close(s)


async def test_http_error_says_what_opencode_said(tmp_path):
    def handler(request):
        return httpx.Response(401, json={'name': 'ProviderAuthError', 'data': {'providerID': 'opencode', 'message': 'Invalid API key'}})

    s = session(tmp_path, handler)
    mid, future = waiting(s, 'A')
    await s._message('A', 'hi', mid)
    assert future.result()['error'] == 'OpenCode message failed: Invalid API key'
    await _close(s)
