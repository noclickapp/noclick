"""What NoClick asks of an OpenClaw gateway: the bridge's time bounds, the
tools it withholds, and receipt reduction for its transcript and chat events."""
from __future__ import annotations

from collections import OrderedDict

# The bridge (openclaw_bridge.mjs, through ``bridge_env``) gives each gateway
# start this long to accept a connection, and one `doctor --fix` repair of
# state an older OpenClaw left its own bound: a large session store takes a
# while to migrate, and a repair cut short never finishes.
GATEWAY_START_S = 60
DOCTOR_S = 180
# The longest the bridge can take to report ready: a start the gateway
# refuses, the repair, and the start after it. Whoever waits on the bridge
# waits at least this long.
BRIDGE_READY_S = 2 * GATEWAY_START_S + DOCTOR_S
# OpenClaw's scheduler never runs in a gateway NoClick owns (the bridge sets
# OPENCLAW_SKIP_CRON), so its scheduling tool would accept a reminder that
# never fires.
DENIED_TOOLS = ("cron",)


def bridge_env() -> dict:
    return {"NOCLICK_OPENCLAW_START_MS": str(GATEWAY_START_S * 1000),
            "NOCLICK_OPENCLAW_DOCTOR_MS": str(DOCTOR_S * 1000)}


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
