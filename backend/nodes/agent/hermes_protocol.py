"""Hermes' public Runs API, with receipt tracking for late steering input.

The client owns no process, filesystem, scheduling, or remote infrastructure.
It can drive any operator-owned Hermes API server with run_steer capability.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid


class HermesClient:
    def __init__(self, base_url, api_key, session_id, *, model='', provider='', instructions=''):
        self.base_url, self.api_key, self.session_id = base_url, api_key, session_id
        self.model, self.provider, self.instructions = model, provider, instructions
        self.active = None
        self.failure = None
        self.inputs = {}
        self.backlog = {}
        self.outbox = queue.Queue()
        self.lock = threading.RLock()
        self.last_activity = time.time()
        self._native_activity = None

    def request(self, method, path, body=None, *, request_id=None):
        headers = {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}
        if request_id:
            headers['Idempotency-Key'] = request_id
        request = urllib.request.Request(self.base_url + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def ready(self):
        capabilities = self.request('GET', '/v1/capabilities')
        if not capabilities.get('features', {}).get('run_steer'):
            raise RuntimeError('This Hermes version lacks Runs API steering; update Hermes to v2026.8.31 or later')

    @staticmethod
    def marked(receipt, text):
        return f'[noclick-input:{receipt}]\n{text}'

    def _start(self, inputs):
        body = {'input': '\n\n'.join(self.marked(r, t) for r, t in inputs.items()),
                'session_id': self.session_id, 'instructions': self.instructions}
        if self.model:
            body['model'] = self.model
        if self.provider:
            body['provider'] = self.provider
        result = self.request('POST', '/v1/runs', body, request_id=str(uuid.uuid4()))
        self.active, self.inputs = result['run_id'], dict(inputs)
        self.last_activity = time.time()

    def send(self, text):
        receipt = str(uuid.uuid4())
        with self.lock:
            if self.failure:
                raise RuntimeError(self.failure)
            self._drain()
            if self.failure:
                raise RuntimeError(self.failure)
            if self.active is None:
                self._start({receipt: text})
            else:
                try:
                    result = self.request('POST', f'/v1/runs/{self.active}/steer',
                                          {'input': self.marked(receipt, text)})
                    if result.get('accepted') is not True:
                        raise RuntimeError('Hermes returned no steering acknowledgement')
                    self.inputs[receipt] = text
                except urllib.error.HTTPError as exc:
                    error = json.loads(exc.read()).get('error') or {}
                    if exc.code != 409 or error.get('code') not in ('run_not_accepting_steer', 'steer_not_accepted'):
                        raise
                    # A definite rejection is safe to queue. It may mean the
                    # run is still booting or has just reached its final result.
                    self.backlog[receipt] = text
                self.last_activity = time.time()
        return receipt

    def _drain(self):
        if self.active is None:
            return
        status = self.request('GET', f'/v1/runs/{self.active}')
        state = status.get('status')
        native_activity = status.get('updated_at')
        if native_activity is not None and native_activity != self._native_activity:
            self.last_activity = time.time()
            self._native_activity = native_activity
        if state not in ('completed', 'failed', 'cancelled', 'interrupted'):
            # Retry only inputs explicitly rejected while the run was queued.
            if state == 'running' and self.backlog:
                for receipt, text in list(self.backlog.items()):
                    try:
                        result = self.request('POST', f'/v1/runs/{self.active}/steer',
                                              {'input': self.marked(receipt, text)})
                    except urllib.error.HTTPError as exc:
                        if exc.code == 409:
                            break
                        raise
                    if result.get('accepted') is not True:
                        raise RuntimeError('Hermes returned no steering acknowledgement')
                    self.inputs[receipt] = text
                    self.backlog.pop(receipt)
            return
        # The API explicitly returns guidance NOT consumed before completion.
        # Only that guidance may be submitted again; never replay the whole run.
        pending = json.dumps(status.get('pending_steer') or '')
        deferred = {r: t for r, t in self.inputs.items() if f'[noclick-input:{r}]' in pending}
        consumed = [r for r in self.inputs if r not in deferred]
        error = None if state == 'completed' else status.get('error') or f'Hermes run {state}'
        if error:
            consumed = list(self.inputs)
            deferred = {}
        if consumed:
            self.outbox.put({'response': status.get('output') or '', 'error': error,
                             'input_ids': consumed, 'usage': status.get('usage') or {}})
        self.active, self.inputs = None, {}
        self.last_activity = time.time()
        deferred.update(self.backlog)
        self.backlog = deferred
        if deferred:
            try:
                self._start(deferred)
            except Exception as exc:
                # The earlier completion is already in the outbox. Report the
                # handoff failure separately and never retry an uncertain start.
                self.failure = f'Hermes follow-up delivery failed: {exc}'
                self.outbox.put({'response': '', 'error': self.failure,
                                 'input_ids': list(deferred), 'usage': {}})
            self.backlog = {}

    def poll_response(self):
        with self.lock:
            if self.outbox.empty():
                self._drain()
            try:
                return self.outbox.get_nowait()
            except queue.Empty:
                return None

    def is_busy(self):
        with self.lock:
            return self.active is not None or bool(self.backlog)

    def stop(self):
        with self.lock:
            if self.active:
                self.request('POST', f'/v1/runs/{self.active}/stop', {})
