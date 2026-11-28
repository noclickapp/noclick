"""Sandboxes: a short-lived Linux box to run code in.

    with noclick.Sandbox.create(image="python", timeout_s=3600) as sb:
        sb.files.write("/tmp/in.csv", csv_bytes)
        print(sb.exec("python -c 'print(1 + 1)'").stdout)
        build = sb.exec("make all", background=True, timeout_s=1800)   # an Operation
        print(build.wait().exit_code)
    # terminated on exit
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Union, overload

from ._client import Client, resolve_client
from ._object import Page, _Object, compact, field, list_all, list_page, parse_time
from ._sync import synced
from ._scope import AMBIENT, resolve_scope
from .exceptions import NotFound
from .operation import Operation, register_result
from .secret import secret_ids, secret_refs
from .volume import volume_ids, volume_refs

# The server's exec timeout when ``timeout_s`` is omitted, plus transport slack.
_DEFAULT_EXEC_S = 60
_EXEC_SLACK_S = 30


@dataclass(frozen=True)
class ExecResult:
    """What a command printed and how it exited (a non-zero ``exit_code`` is a result, not an error)."""

    stdout: str
    stderr: str
    exit_code: Optional[int]
    raw: Dict[str, Any] = dc_field(repr=False)

    @property
    def ok(self) -> bool:
        """Whether the command exited 0."""
        return self.exit_code == 0

    def __str__(self) -> str:
        return self.stdout

    @classmethod
    def _from(cls, raw: Any) -> "ExecResult":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("stdout") or "", raw.get("stderr") or "", raw.get("exit_code"), raw)


def _read_exec(result: Any, op: Operation) -> ExecResult:
    return ExecResult._from(result)


register_result("sandbox.exec", _read_exec)


@dataclass(frozen=True)
class CodeSandboxShell:
    """An interactive shell in a sandbox (``sandbox.shell()``): ``url`` is a websocket, opened once with ``token``
    within two minutes. Its first message is ``{"type": "auth", "token": ..., "cols": ..., "rows": ...}``; then binary
    messages carry what you type and what it prints, a text ``{"type": "resize", "cols", "rows"}`` sizes it, and it
    sends ``{"type": "ready"}`` once and ``{"type": "state", "state": "exited", "reason", "exit_code"}`` as it closes
    (code 4410): bash exited, ``idle_limit_s`` passed with nothing typed, or the socket closed. It closes 4401 once its
    key is revoked or expires and 4404 once the sandbox stops."""

    sandbox_id: str
    url: str
    token: str = dc_field(repr=False)  # opens the shell: never in a log line
    token_expires_at: Any
    idle_limit_s: int

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "CodeSandboxShell":
        return cls(raw["sandbox_id"], raw["url"], raw["token"], parse_time(raw.get("token_expires_at")),
                   int(raw["idle_limit_s"]))


class SandboxFiles:
    """``sb.files``: read and write files inside the sandbox."""

    def __init__(self, sandbox: "Sandbox") -> None:
        self._sandbox = sandbox

    def __repr__(self) -> str:
        return f"SandboxFiles(sandbox={self._sandbox._known('id')!r})"

    @synced
    async def write(self, path: str, data: Union[bytes, str]) -> None:
        """Write ``data`` (bytes, or text as UTF-8) to ``path``, replacing it.

        Usage::

            with noclick.Sandbox.create(image="python") as sb:
                sb.files.write("/workspace/main.py", "print('hello from the sandbox')")
                print(sb.exec("python main.py").stdout)   # hello from the sandbox
        """
        content = data.encode() if isinstance(data, str) else bytes(data)
        await self._sandbox._request(
            "PUT", f"{self._sandbox._path()}/files", params={"path": path}, content=content,
        )

    @synced
    async def read(self, path: str) -> bytes:
        """Read the file at ``path``; a missing file raises ``noclick.NotFound``.

        Returns:
            The file's bytes, exactly as stored; decode text yourself.

        Usage::

            with noclick.Sandbox.create() as sb:
                sb.exec("echo done > /workspace/out.txt")
                print(sb.files.read("/workspace/out.txt").decode())   # done
        """
        return await self._sandbox._request(
            "GET", f"{self._sandbox._path()}/files", params={"path": path}, binary=True,
        )


def network_wire(network: Any) -> Any:
    """``network=`` on the wire: ``True``/``False``, or the hosts (``*.domain`` included) it may reach."""
    if network is None or isinstance(network, bool):
        return network
    if isinstance(network, str) or not all(isinstance(host, str) for host in network):
        raise TypeError(f"network is True, False or a list of hosts, not {network!r}")
    return list(network)


class Sandbox(_Object):
    """A running sandbox. ``with noclick.Sandbox.create() as sb:`` terminates it on exit;
    otherwise it stops at ``expires_at``. Billed per second while it runs, at its
    provider's price for the ``cpu`` and ``memory_mb`` it reserves."""

    _repr_keys = ("id", "status", "image")

    id: str = field("id")
    status: Optional[str] = field("status")
    image: Optional[str] = field("image")
    timeout_s: Optional[int] = field("timeout_s")
    cpu: Optional[float] = field("cpu")
    memory_mb: Optional[int] = field("memory_mb")
    region: Optional[str] = field(
        "region", doc="The region it runs in (``noclick.regions()``), or ``None``: wherever NoClick had capacity.",
    )
    user_id: Optional[str] = field("user_id")
    expires_at: Any = field("expires_at", parse_time)
    created_at: Any = field("created_at", parse_time)
    volumes: Optional[Dict[str, str]] = field(
        "volumes", doc="The volumes it mounts, by mount path: ``{path: volume id}``.",
    )
    secret_ids: Optional[List[str]] = field(
        "secret_ids", doc="The secrets in its environment, in order (a later one's key wins).",
    )
    network: Any = field(
        "network",
        doc="What it may reach: ``False`` (nothing), ``True`` (anywhere) or the hosts it may reach, as sent.",
    )

    @property
    def files(self) -> SandboxFiles:
        return SandboxFiles(self)

    @synced
    @classmethod
    async def create(
        cls,
        image: Optional[str] = None,
        *,
        timeout_s: Optional[int] = None,
        cpu: Optional[float] = None,
        memory_mb: Optional[int] = None,
        network: Union[None, bool, Sequence[str]] = None,
        region: Optional[str] = None,
        volumes: Optional[Mapping[str, Any]] = None,
        secrets: Optional[Sequence[Any]] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Sandbox":
        """Start a sandbox (``image`` ``"python"`` or ``"node"``) that lives
        at most ``timeout_s`` seconds. ``network=True`` allows outbound
        internet access, which is off by default. A list of up to 50 hosts allows
        only those, over HTTPS on port 443: ``"pypi.org"``, or ``"*.example.com"`` for a
        domain and its subdomains (a scheme, path, port or IP address raises
        ``noclick.InvalidRequest``).

        ``region`` is where it runs (``noclick.regions()``): ``region=agent.region``
        puts it beside an agent. Without one it runs in your account's default
        region, else wherever NoClick has capacity. Pinned to a region it costs what the
        provider charges there: 1.15x in ``eu`` and ``ap``, 1.75x in ``us-east`` and ``us-west``.

        ``volumes`` mounts ``Volume``s (or their ids or names) read-write at
        absolute paths, ``{"/data": vol}``, up to 5: the sandbox sees each as it
        was when it started, and what it writes there is saved every few seconds
        while it runs, and all of it when it ends. A path can't be ``/``,
        ``/workspace`` itself or a system folder.

        ``secrets`` (``Secret``s, ids or names; up to 20) become environment
        variables for every command, a later secret's key winning a clash; the
        sandbox keeps the values it started with. A volume's or secret's name is
        the sandbox's user's own, else the account's (a user session's, its own only).

        Returns:
            The sandbox, ``running`` and ready for commands. It stops on its own at ``expires_at``.

        Usage:
            Use it as a context manager, so it stops when the block ends::

                with noclick.Sandbox.create(image="python", timeout_s=600) as sb:
                    print(sb.exec("python -c 'print(21 * 2)'").stdout)   # 42

            Without ``with``, stop it yourself or let it run out::

                sb = noclick.Sandbox.create(image="node", timeout_s=300, network=True)
                print(sb.id, sb.expires_at)
                sb.terminate()

            Run it in Europe, beside an agent that works there::

                with noclick.Sandbox.create(region="eu") as sb:
                    print(sb.region)   # eu

            Reach only the package index::

                with noclick.Sandbox.create(image="python", network=["pypi.org", "files.pythonhosted.org"]) as sb:
                    sb.exec("pip install requests")

            Mount a volume and pass a secret, so the job reads its data, calls its API and leaves its
            output for the next run::

                data = noclick.Volume.from_name("datasets", create_if_missing=True)
                openai = noclick.Secret.from_name("openai")
                with noclick.Sandbox.create(volumes={"/data": data}, secrets=[openai], network=True) as sb:
                    sb.exec("python summarize.py --in /data/raw --out /data/summaries")
        """
        scope = resolve_scope(user)
        mounts = volume_refs(volumes, user=scope, client=client)
        env = secret_refs(secrets, user=scope, client=client)
        raw = await resolve_client(client).request(
            "POST", "/v1/sandboxes",
            json=compact(
                image=image, timeout_s=timeout_s, cpu=cpu, memory_mb=memory_mb, network=network_wire(network),
                region=region,
                volumes=None if mounts is None else await volume_ids(mounts),
                secret_ids=None if env is None else await secret_ids(env),
            ),
            user=scope,
        )
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_id(cls, sandbox_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Sandbox":
        """A lazy reference to a sandbox by id, for one you started earlier.

        Returns:
            A sandbox that loads the first time you read a field. Nothing is sent yet.

        Usage::

            sb = noclick.Sandbox.from_id("5e0c7a1d-2b9f-4d3e-8a61-7f2c9b4e1d08")
            print(sb.exec("ls -la").stdout)
        """
        return cls._new(hints={"id": sandbox_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, sandbox_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Sandbox":
        """Load a sandbox by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The sandbox, loaded. Its ``status`` is ``starting``, ``running``, ``terminated`` or ``failed``.

        Usage::

            sb = noclick.Sandbox.get("5e0c7a1d-2b9f-4d3e-8a61-7f2c9b4e1d08")
            print(sb.status, sb.expires_at)
        """
        sandbox = cls.from_id(sandbox_id, client=client, user=user)
        await sandbox._ensure()
        return sandbox

    @synced
    @classmethod
    async def list(
        cls, *, status: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Sandbox"]:
        """List the current user's sandboxes (the account's own outside ``as_user``, or
        those ``user_filter`` covers); ``status="live"`` lists those starting or running.

        Returns:
            Every matching sandbox, newest first, fetched page by page.

        Usage:
            The sandboxes still starting or running::

                for sb in noclick.Sandbox.list(status="live"):
                    print(sb.id, sb.image, sb.expires_at)

            Every user's, plus your account's own::

                sandboxes = noclick.Sandbox.list(user_filter=noclick.ALL_USERS, limit=50)
        """
        return await list_all(
            "/v1/sandboxes", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"status": status}, user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, status: Optional[str] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of sandboxes; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the sandboxes and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Sandbox.list_page(status="terminated", limit=50)
            while True:
                for sb in page.data:
                    print(sb.id, sb.created_at)
                if page.next_cursor is None:
                    break
                page = noclick.Sandbox.list_page(status="terminated", limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/sandboxes", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"status": status}, user=user, user_filter=user_filter, cursor=cursor, limit=limit,
            client=client,
        )

    def _path(self) -> str:
        return f"/v1/sandboxes/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    @overload
    async def exec(
        self, command: Union[str, Sequence[str]], *, background: Literal[False] = False, timeout_s: Optional[int] = None,
    ) -> ExecResult: ...

    @overload
    async def exec(
        self, command: Union[str, Sequence[str]], *, background: Literal[True], timeout_s: Optional[int] = None,
    ) -> Operation: ...

    @synced
    async def exec(
        self, command: Union[str, Sequence[str]], *, background: bool = False, timeout_s: Optional[int] = None,
    ) -> Union[ExecResult, Operation]:
        """Run a shell command (a string, or an argv list that gets quoted)
        and wait for it: ``timeout_s`` is 60 by default, at most 90. A
        non-zero exit is a result, not an exception.

        ``background=True`` is for commands longer than one request allows
        (``timeout_s`` up to 3600, within the sandbox's own lifetime).

        Returns:
            What the command printed and how it exited: ``stdout`` and ``stderr`` (the last 64 KiB of each)
            and ``exit_code``. With ``background=True``, an ``Operation`` at once, whose ``wait()`` gives that result.

        Usage:
            Commands run with bash in ``/workspace``. Check ``ok`` or ``exit_code``, since a failing command
            doesn't raise::

                with noclick.Sandbox.create() as sb:
                    result = sb.exec("python -c 'print(21 * 2)'")
                    print(result.ok, result.stdout)   # True 42
                    sb.exec(["python", "script.py", "--input", "data.csv"])   # an argument list is quoted for you

            Run anything longer in the background, in a sandbox that lives long enough to finish it::

                with noclick.Sandbox.create(timeout_s=3600) as sb:
                    build = sb.exec("make all", background=True, timeout_s=1800)
                    print(build.wait().exit_code)
        """
        if not isinstance(command, str):
            command = shlex.join(command)
        if background:
            payload = await self._request(
                "POST", f"{self._path()}/exec", json=compact(command=command, background=True, timeout_s=timeout_s),
            )
            return Operation._from_payload(
                payload, client=self._client, user=self._call_scope(), kind="sandbox.exec",
                reader=_read_exec,
            )
        raw = await self._request(
            "POST", f"{self._path()}/exec", json=compact(command=command, timeout_s=timeout_s),
            timeout=(timeout_s or _DEFAULT_EXEC_S) + _EXEC_SLACK_S,
        )
        return ExecResult._from(raw)

    @synced
    async def shell(self) -> CodeSandboxShell:
        """Open an interactive shell (``bash -l`` in ``/workspace``, in a PTY) in this running sandbox.
        ``noclick shell <sandbox>`` opens one in your own terminal.

        Returns:
            The websocket's ``url`` and its single-use ``token`` (good for two minutes): hand them to a browser
            terminal (xterm.js) from your server.

        Usage::

            sb = noclick.Sandbox.from_id("3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40")
            opened = sb.shell()
            send_to_browser(opened.url, opened.token)
        """
        return CodeSandboxShell._from(await self._request("POST", f"{self._path()}/shell"))

    @synced
    async def terminate(self) -> None:
        """Stop the sandbox now (billing stops with it).

        Usage::

            sb = noclick.Sandbox.create()
            try:
                print(sb.exec("uname -a").stdout)
            finally:
                sb.terminate()
        """
        await self._request("DELETE", self._path())
        self._raw = {**(self._raw or {}), "status": "terminated"}

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.terminate()
        except NotFound:  # it already expired
            pass

    async def __aenter__(self) -> "Sandbox":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        try:
            await self.terminate.aio()
        except NotFound:  # it already expired
            pass
