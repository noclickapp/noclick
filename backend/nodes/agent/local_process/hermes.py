"""Run an operator-owned Hermes gateway as a local child process."""
from __future__ import annotations

import asyncio
import urllib.error

from nodes.agent.hermes_protocol import HermesClient
from .session import Session


class HermesSession(Session):
    mode = "steering"

    def __init__(self, *, base_url, api_key, model, provider, **kwargs):
        super().__init__(**kwargs)
        self.client = HermesClient(base_url, api_key, 'noclick', model=model, provider=provider)
        self.receipts = {}
        self.results = []

    async def start(self):
        await super().start()
        self.task(self._stdout())
        async with asyncio.timeout(60):
            while True:
                if self.proc.returncode is not None:
                    raise RuntimeError(self.stderr.decode(errors='replace') or 'Hermes gateway exited')
                try:
                    await asyncio.to_thread(self.client.ready)
                    break
                except (urllib.error.URLError, ConnectionError, OSError):
                    await asyncio.sleep(.1)
        self.task(self._poll())

    async def _stdout(self):
        while await self.proc.stdout.read(4096):
            pass
        await self.proc.wait()
        if not self.closed:
            await self.close(self.stderr.decode(errors='replace') or 'Hermes gateway exited')

    async def send(self, receipt, text):
        native = await asyncio.to_thread(self.client.send, text)
        self.receipts[native] = receipt
        self._flush()

    def _flush(self):
        while self.results and all(r in self.receipts for r in self.results[0]['input_ids']):
            result = self.results.pop(0)
            self.complete([self.receipts.pop(r) for r in result['input_ids']],
                          result['response'], result['error'])

    async def _poll(self):
        try:
            while True:
                result = await asyncio.to_thread(self.client.poll_response)
                if result is not None:
                    self.results.append(result)
                    self._flush()
                await asyncio.sleep(.1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.close(f'Hermes gateway failed: {exc}')
