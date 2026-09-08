"""Local process lifetime and response ownership; no remote infrastructure."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import weakref
from collections import OrderedDict
from pathlib import Path
from typing import Callable
from uuid import uuid4

from nodes.agent.cli_protocol import RpcError

IDLE_TIMEOUT_S = float(os.environ.get("NOCLICK_LOCAL_AGENT_IDLE_TIMEOUT", "60"))
# A pipe breaks before the child's exit is observed; this is how long a failed
# delivery waits to learn whether the child is gone before blaming the pipe.
DELIVERY_EXIT_GRACE_S = 1.0


class Session:
    mode = "queued"

    def __init__(self, *, workdir: Path, env: dict, command: list, cleanup: Callable):
        self.workdir, self.env, self.command = workdir, env, command
        self.cleanup = cleanup
        self.pending: OrderedDict[str, asyncio.Future] = OrderedDict()
        self.activations = {}
        self.idle = asyncio.Event()
        self.idle.set()
        self.closed = False
        self.stopped = asyncio.Event()
        self.proc = None
        self.tasks: set[asyncio.Task] = set()
        self.stderr = b""
        self._stderr_task = None
        self._idle_task = None
        self._close_task = None

    def task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            *self.command, cwd=self.workdir, env=self.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=4 * 1024 * 1024,
            start_new_session=os.name == "posix",
        )
        self._stderr_task = self.task(self._read_stderr())

    async def _read_stderr(self):
        while data := await self.proc.stderr.read(4096):
            self.stderr = (self.stderr + data)[-16384:]

    async def submit(self, text: str, activate=lambda session: None):
        if self.closed:
            raise RuntimeError("Local agent session is closed")
        if self._idle_task:
            self._idle_task.cancel()
        receipt = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[receipt] = future
        self.activations[receipt] = activate
        future.add_done_callback(lambda _: self.activate_owner())
        self.activate_owner()
        self.idle.clear()
        try:
            await self.send(receipt, text)
        except Exception as exc:
            # Uncertain delivery is terminal; never replay a possibly accepted
            # input. A child that died before reading owns the story: its
            # stderr says why (not signed in, a bad flag) and the broken pipe
            # is only the symptom, so it must not beat the exit reader to
            # the future.
            await self.close(
                await self.exit_error() if await self.exited()
                else f"Local agent delivery failed: {exc}"
            )
        return future

    async def exited(self) -> bool:
        """Whether the child is gone: reaped already, or within the grace."""
        if self.proc is None:
            return False
        if self.proc.returncode is not None:
            return True
        try:
            await asyncio.wait_for(self.proc.wait(), DELIVERY_EXIT_GRACE_S)
        except asyncio.TimeoutError:
            return False
        return True

    async def exit_error(self) -> str:
        """The exited child's own account: its diagnostic output, else its
        exit code. The drain is bounded because a tool child that inherited
        the pipe can hold it open past its parent's exit."""
        if self._stderr_task is not None and not self._stderr_task.done():
            await asyncio.wait({self._stderr_task}, timeout=0.5)
        detail = self.stderr.decode(errors="replace").strip()
        return detail or f"Local agent exited with code {self.proc.returncode}"

    async def send(self, receipt, text):
        raise NotImplementedError

    def activate_owner(self):
        for receipt, future in self.pending.items():
            if not future.done():
                self.activations[receipt](self)
                break

    def complete(self, receipts, response="", error=None):
        owner = True
        for receipt in receipts:
            future = self.pending.pop(receipt, None)
            self.activations.pop(receipt, None)
            if future is None or future.done():
                continue
            result = {"response": response, "error": error, "input_mode": self.mode}
            if not owner:
                result.update(skipped=True, response="")
            future.set_result(result)
            owner = False
        self.activate_owner()
        if not self.pending:
            self.idle.set()
            if not self.closed:
                self._idle_task = self.task(self._expire())

    async def _expire(self):
        await asyncio.sleep(IDLE_TIMEOUT_S)
        await self.close()

    async def close(self, error="Local agent session stopped"):
        if self._close_task is None:
            self.closed = True
            self._close_task = asyncio.create_task(self._close(error, asyncio.current_task()))
        # Request cancellation cannot interrupt process and credential cleanup.
        await asyncio.shield(self._close_task)

    async def _close(self, error, caller):
        self.complete(list(self.pending), error=error)
        tasks = [task for task in self.tasks if task is not caller]
        for task in tasks:
            task.cancel()
        if self.proc and self.proc.returncode is None:
            try:
                self._signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError:
                self._signal(signal.SIGKILL)
                await self.proc.wait()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # A tool child can survive its CLI parent exiting first.
        if self.proc and os.name == "posix":
            self._signal(signal.SIGKILL)
        try:
            self.cleanup()
        finally:
            self.stopped.set()

    def _signal(self, sig):
        try:
            if os.name == "posix":
                os.killpg(self.proc.pid, sig)
            elif sig == signal.SIGTERM:
                self.proc.terminate()
            else:
                self.proc.kill()
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS can reject a process-group signal during child exit. The
            # subprocess handle can still terminate a live parent directly.
            if self.proc.returncode is None:
                try:
                    self.proc.send_signal(sig)
                except ProcessLookupError:
                    pass


class LineSession(Session):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._requests = {}
        self._request_id = 0

    async def start(self):
        await super().start()
        self.task(self._read())

    async def write(self, value):
        self.proc.stdin.write((json.dumps(value) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, method, params):
        self._request_id += 1
        rid = self._request_id
        future = asyncio.get_running_loop().create_future()
        self._requests[rid] = future
        try:
            await self.write({"id": rid, "method": method, "params": params})
            return await asyncio.wait_for(future, 60)
        finally:
            self._requests.pop(rid, None)

    async def _read(self):
        try:
            async for line in self.proc.stdout:
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(event, dict):
                    continue
                if "id" in event and ("result" in event or "error" in event):
                    future = self._requests.get(event["id"])
                    if future is not None and not future.done():
                        if "error" in event:
                            future.set_exception(RpcError(event["error"]))
                        else:
                            future.set_result(event.get("result"))
                elif "id" in event and "method" in event:
                    # Headless requests must receive an answer instead of hanging.
                    await self.write({"id": event["id"], "error": {
                        "code": -32601, "message": "Interactive input is unavailable"}})
                else:
                    self.on_event(event)
            await self.proc.wait()
            await self.close(await self.exit_error())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.close(f"Local agent protocol failed: {exc}")

    async def close(self, error="Local agent session stopped"):
        for future in self._requests.values():
            if not future.done():
                future.set_exception(RuntimeError(error))
        await super().close(error)

    def on_event(self, event):
        raise NotImplementedError


class Sessions:
    """One session per scoped conversation; independent keys never share a lock.

    This registry belongs to one backend process. Multiple local backend workers
    need explicit affinity for the conversation key; this is not a distributed
    coordinator. Local CLI processes already run concurrently across keys.
    """

    def __init__(self):
        self.entries = {}
        self.locks = weakref.WeakValueDictionary()

    async def submit(self, key, fingerprint, factory, text, activate):
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = self.entries.get(key)
            if entry and entry[1].closed:
                await entry[1].stopped.wait()
            if entry and entry[0] != fingerprint:
                # Never rewrite live credentials/config while a turn uses them.
                await entry[1].idle.wait()
                await entry[1].close()
            entry = self.entries.get(key)
            if not entry or entry[0] != fingerprint or entry[1].closed:
                session = await factory()
                self.entries[key] = (fingerprint, session)
                original_cleanup = session.cleanup
                def cleanup():
                    original_cleanup()
                    if self.entries.get(key, (None, None))[1] is session:
                        self.entries.pop(key, None)
                session.cleanup = cleanup
                try:
                    await session.start()
                except BaseException:
                    await session.close("Local agent could not start")
                    raise
            else:
                session = entry[1]
            try:
                future = await session.submit(text(session) if callable(text) else text, activate)
            except BaseException:
                await session.close("Local agent delivery cancelled")
                raise
        return session, future

    async def close(self):
        await asyncio.gather(*(entry[1].close() for entry in list(self.entries.values())))
        self.entries.clear()
        self.locks.clear()


sessions = Sessions()
