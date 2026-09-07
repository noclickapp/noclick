"""Receipt reduction for OpenClaw's public gateway transcript and chat events."""
from __future__ import annotations

from collections import OrderedDict


class OpenClawReceipts:
    def __init__(self, session_key):
        self.session_key = session_key
        self.pending = OrderedDict()
        self.finished = OrderedDict()

    def add(self, receipt):
        self.pending[receipt] = receipt

    def accepted(self, receipt, response):
        if self.pending.get(receipt) == receipt:
            self.pending[receipt] = response.get('runId') or receipt

    def observe(self, event, payload):
        if payload.get('sessionKey') != self.session_key:
            return None
        if event == 'session.message':
            message = payload.get('message') or {}
            if message.get('role') == 'user':
                metadata = message.get('__openclaw') or {}
                key = metadata.get('idempotencyKey') or message.get('idempotencyKey') or ''
                receipt = key.removesuffix(':user')
                target = metadata.get('steerTargetRunId')
                if receipt in self.pending and target:
                    self.pending[receipt] = target
            return None
        if event != 'chat' or payload.get('state') not in ('final', 'error', 'aborted'):
            return None
        run = payload.get('runId')
        if run in self.finished:
            return None
        receipts = [receipt for receipt, target in self.pending.items() if target == run]
        if not receipts:
            # A steered input has its own empty final event. Its transcript
            # receipt identifies the actual owner, whose completion carries it.
            return None
        self.finished[run] = None
        if len(self.finished) > 256:
            self.finished.popitem(last=False)
        for receipt in receipts:
            self.pending.pop(receipt)
        message = payload.get('message') or {}
        content = message.get('content') or []
        text = content if isinstance(content, str) else ''.join(p.get('text', '') for p in content if p.get('type') == 'text')
        error = None if payload['state'] == 'final' else payload.get('errorMessage') or f"OpenClaw run {payload['state']}"
        return {'response': text, 'error': error, 'input_ids': receipts}
