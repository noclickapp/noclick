"""A local gateway session using OpenClaw's native queueMode=steer path."""
import asyncio
import hashlib

from nodes.agent.openclaw_protocol import OpenClawReceipts
from .session import LineSession


class OpenClawSession(LineSession):
    mode = 'steering'

    def __init__(self, *, session_key='agent:main:noclick', **kwargs):
        super().__init__(**kwargs)
        self.session_key = session_key
        self.receipts = OpenClawReceipts(session_key)
        self.ready = asyncio.Event()

    async def start(self):
        await super().start()
        async with asyncio.timeout(60):
            while not self.ready.is_set():
                if self.closed:
                    raise RuntimeError(self.stderr.decode(errors='replace') or 'OpenClaw gateway could not start')
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
