"""Public streaming protocols for locally installed coding agents."""
from __future__ import annotations

import asyncio
from collections import OrderedDict

import httpx

from nodes.agent.cli_protocol import ClaudeReceipts, RpcError, steer_turn_ended
from .session import LineSession, Session


class ClaudeSession(LineSession):
    mode = "streaming"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.receipts = ClaudeReceipts()
        self.has_history = False

    async def send(self, receipt, text):
        self.receipts.add(receipt)
        await self.write({"type": "user", "uuid": receipt,
                          "message": {"role": "user", "content": text}})

    def on_event(self, event):
        if event.get("type") == "user":
            self.receipts.observe(event)
        elif event.get("type") == "assistant":
            self.has_history = True
        elif event.get("type") == "result":
            failed = event.get("is_error") or event.get("subtype") != "success"
            error = (event.get("error") or event.get("result") or
                     f"Claude turn ended: {event.get('subtype')}") if failed else None
            self.complete(self.receipts.finish(event), event.get("result") or "", error)
            if not failed or self.has_history:
                (self.workdir / ".noclick-turns").touch()


class CodexSession(LineSession):
    mode = "steering"

    def __init__(self, *, model, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.thread = None
        self.active = None
        self.receipts = {}
        self.text = {}
        self.finished = {}

    async def start(self):
        await super().start()
        await self.request("initialize", {"clientInfo": {
            "name": "codex_app_server_daemon", "title": "NoClick", "version": "1.0.0"}})
        await self.write({"method": "initialized", "params": {}})
        path = self.workdir / ".noclick-codex-thread"
        params = {"cwd": str(self.workdir), "approvalPolicy": "never", "sandbox": "workspace-write"}
        if self.model:
            params["model"] = self.model
        if path.exists():
            result = await self.request("thread/resume", {**params, "threadId": path.read_text().strip()})
        else:
            result = await self.request("thread/start", params)
        self.thread = result["thread"]["id"]
        path.write_text(self.thread)

    async def send(self, receipt, text):
        inputs = [{"type": "text", "text": text}]
        active = self.active
        if active:
            # Register before awaiting the RPC: completion may beat its ack.
            self.receipts.setdefault(active, []).append(receipt)
            try:
                await self.request("turn/steer", {
                    "threadId": self.thread, "input": inputs, "expectedTurnId": active})
                self._flush(active)
                return
            except RpcError as exc:
                self.receipts[active].remove(receipt)
                self._flush(active)
                if not steer_turn_ended(exc):
                    raise
            # A timeout or broken connection deliberately does not reach here.
        result = await self.request("turn/start", {
            "threadId": self.thread, "input": inputs, **({"model": self.model} if self.model else {})})
        tid = result["turn"]["id"]
        self.receipts.setdefault(tid, []).append(receipt)
        if tid not in self.finished:
            self.active = tid
        self._flush(tid)

    def on_event(self, event):
        method, params = event.get("method"), event.get("params") or {}
        if method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "agentMessage":
                self.text.setdefault(params.get("turnId"), []).append(item.get("text", ""))
        elif method in ("turn/completed", "turn/failed"):
            turn = params.get("turn") or {}
            tid = turn.get("id") or params.get("turnId")
            if self.active == tid:
                self.active = None
            status = turn.get("status") or ("failed" if method == "turn/failed" else "completed")
            error = None if status == "completed" else turn.get("error") or f"Codex turn {status}"
            self.finished[tid] = ("".join(self.text.pop(tid, [])), error)
            # Defer while send awaits an acknowledgement. It owns registration
            # and rejection handling, so rejected input cannot inherit this turn.
            if not self._requests:
                self._flush(tid)

    def _flush(self, tid):
        if tid in self.finished and self.receipts.get(tid):
            text, error = self.finished.pop(tid)
            self.complete(self.receipts.pop(tid), text, error)


class OpenCodeSession(Session):
    mode = "steering"

    def __init__(self, *, model, base_url, password, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.http = httpx.AsyncClient(base_url=base_url, auth=("opencode", password), timeout=900)
        self.session_id = ""
        self.seen = OrderedDict()
        self.message_ids = {}

    async def start(self):
        await super().start()
        # The server logs on stdout; drain it to avoid blocking long sessions.
        self.task(self._stdout())
        for _ in range(300):
            if self.proc.returncode is not None:
                raise RuntimeError("OpenCode server exited before becoming ready")
            try:
                response = await self.http.get("/global/health", timeout=1)
                response.raise_for_status()
                break
            except (httpx.HTTPError, OSError):
                await asyncio.sleep(.1)
        else:
            raise RuntimeError("OpenCode server did not become ready")
        path = self.workdir / ".noclick-opencode-session"
        if path.exists():
            self.session_id = path.read_text().strip()
            response = await self.http.get(f"/session/{self.session_id}")
            response.raise_for_status()
        else:
            response = await self.http.post("/session", json={})
            response.raise_for_status()
            self.session_id = response.json()["id"]
            path.write_text(self.session_id)

    async def _stdout(self):
        while await self.proc.stdout.read(4096):
            pass
        await self.proc.wait()
        if not self.closed:
            await self.close(f"OpenCode server exited with code {self.proc.returncode}")

    async def send(self, receipt, text):
        mid = "msg_" + receipt.replace("-", "")
        self.message_ids[mid] = receipt
        future = self.pending[receipt]
        self.task(self._message(receipt, text, mid))
        # Preserve the order in which the CLI accepts user messages without
        # waiting for the model. Parent IDs can then identify an exact prefix.
        async with asyncio.timeout(60):
            while not future.done():
                response = await self.http.get(f"/session/{self.session_id}/message", params={"limit": 100})
                response.raise_for_status()
                if any((m.get("info") or {}).get("id") == mid for m in response.json()):
                    break
                await asyncio.sleep(.02)

    async def _message(self, receipt, text, message_id):
        try:
            body = {"messageID": message_id, "parts": [{"type": "text", "text": text}]}
            if self.model:
                provider, _, model = self.model.partition("/")
                if not model:
                    raise ValueError("OpenCode model must be provider/model")
                body["model"] = {"providerID": provider, "modelID": model}
            # Concurrent synchronous requests join OpenCode's live session loop.
            # Each remains subscribed to completion, including at the idle race.
            response = await self.http.post(f"/session/{self.session_id}/message", json=body)
            response.raise_for_status()
            data = response.json()
            info = data.get("info") or {}
            mid = info.get("id")
            if not mid or info.get("role") != "assistant":
                raise RuntimeError("OpenCode returned no identifiable assistant response")
            if mid in self.seen or receipt not in self.pending:
                return
            self.seen[mid] = None
            if len(self.seen) > 256:
                self.seen.popitem(last=False)
            text = "".join(p.get("text", "") for p in data.get("parts", []) if p.get("type") == "text")
            parent = self.message_ids.get(info.get("parentID"))
            if parent not in self.pending:
                raise RuntimeError("OpenCode returned an unknown response parent")
            ids = list(self.pending)
            consumed = ids[:ids.index(parent) + 1]
            self.complete(consumed, text, info.get("error"))
            self.message_ids = {mid: rid for mid, rid in self.message_ids.items() if rid not in consumed}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # No replay after an uncertain HTTP response.
            await self.close(f"OpenCode message failed: {exc}")

    async def close(self, error="Local agent session stopped"):
        await super().close(error)
        await self.http.aclose()
