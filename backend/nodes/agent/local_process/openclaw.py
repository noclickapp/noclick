"""A local gateway session using OpenClaw's native queueMode=steer path."""
import asyncio
import hashlib

from nodes.agent.openclaw_protocol import BRIDGE_READY_S, OpenClawReceipts
from nodes.core.base import FailureWithDiagnostics
from .session import LineSession

# Outwaits the bridge's worst case (a refused start, a state repair, a start).
GATEWAY_READY_S = BRIDGE_READY_S + 5


class OpenClawSession(LineSession):
    mode = 'steering'

    def __init__(self, *, session_key='agent:main:noclick', **kwargs):
        super().__init__(**kwargs)
        self.session_key = session_key
        self.receipts = OpenClawReceipts(session_key)
        self.ready = asyncio.Event()

    async def start(self):
        await super().start()
        async with asyncio.timeout(GATEWAY_READY_S):
            while not self.ready.is_set():
                if self.closed:
                    raise self._start_failure()
                await asyncio.sleep(.02)
        legacy = 'noclick-' + hashlib.sha256(str(self.workdir).encode()).hexdigest()[:16]
        resolved = await self.request('sessions.resolve', {
            'sessionId': legacy, 'agentId': 'main', 'allowMissing': True})
        if resolved.get('key'):
            self.session_key = resolved['key']
            self.receipts.session_key = self.session_key
        elif any((self.workdir / '.openclaw').glob(f'agents/*/sessions/{legacy}.jsonl')):
            raise RuntimeError('OpenClaw could not resolve the existing conversation')
        await self.request('sessions.messages.subscribe', {'key': self.session_key})

    def _start_failure(self):
        """The bridge's output (the gateway's, and a state repair's) can quote
        the config it was given: a person reads that the gateway didn't start,
        and only the diagnostics carry the end of that output."""
        shown = 'OpenClaw gateway could not start'
        tail = self.stderr.decode(errors='replace').strip()
        if len(tail) > 1500:
            tail = tail[-1500:].split('\n', 1)[-1]  # whole lines only
        return FailureWithDiagnostics(shown, f'{shown}\n{tail}' if tail else shown)

    async def send(self, receipt, text):
        self.receipts.add(receipt)
        result = await self.request('chat.send', {'sessionKey': self.session_key,
            'message': text, 'idempotencyKey': receipt, 'queueMode': 'steer'})
        self.receipts.accepted(receipt, result)

    def on_event(self, event):
        if event.get('method') == 'bridge/ready':
            self.ready.set()
            return
        result = self.receipts.observe(event.get('method'), event.get('params') or {})
        if result:
            self.complete(result['input_ids'], result['response'], result['error'])
