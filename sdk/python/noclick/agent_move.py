"""Moves: a coding agent's session on a laptop (Claude Code, Codex, OpenCode, Hermes or OpenClaw) copies itself
onto a NoClick agent and carries on there. The laptop keeps its own session.

Your side makes the move and follows it; the agent in the session does the rest, from the guide its prompt names:

    move = noclick.AgentMove.create(name="Docs fixer")
    print(move.prompt)        # paste into the session you want moved
    ...
    move.refresh()
    print(move.status, move.arrived["files"])   # moving, what it carried so far
    print(move.agent_id, move.conversation)     # once done

The agent's side runs with the move's own key, which its code is redeemed for once (``AgentMove.redeem``): it can
reach nothing but the move, and ends with it.

    key = noclick.AgentMove.redeem("nc_move_...", host="ana-mbp")
    moving = noclick.AgentMove.current(client=noclick.Client(api_key=key))
    moving.upload_session(tar_bytes, harness="claude_code", cwd="/Users/ana/code/acme")
    moving.finish()
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import quote

import httpx

from ._client import API_URL_ENV, DEFAULT_BASE_URL, Client, resolve_client
from ._object import _Object, compact, field, parse_time, ref_id
from ._scope import AMBIENT
from ._sync import synced
from .exceptions import OperationFailed, error_from_payload

MOVE_STATUSES = ("waiting", "moving", "finishing", "done", "failed", "canceled", "expired")
# How often ``finish`` reads a move whose finish NoClick is running.
FINISH_POLL_S = 2.0


class AgentMove(_Object):
    """A move from a laptop: ``waiting`` for its code to be redeemed, ``moving`` while what the agent carries
    arrives (``arrived``), ``finishing`` while the agent is made (``steps``), then ``done`` with ``agent_id`` and
    ``conversation``; ``failed`` (finish again), ``canceled`` or ``expired``."""

    _repr_keys = ("id", "status")

    id: str = field("id")
    status: str = field("status", doc="One of ``waiting``, ``moving``, ``finishing``, ``done``, ``failed``, "
                                      "``canceled``, ``expired``.")
    code: Optional[str] = field("code", doc="The one-time code (from ``create`` only): it works once, for 30 minutes.")
    prompt: Optional[str] = field(
        "prompt", doc="What a person pastes into the session to move (from ``create`` only): the guide and the code.")
    guide_url: str = field("guide_url", doc="The guide the moving agent follows.")
    workspace_id: Optional[str] = field("workspace_id", doc="The space the agent joins.")
    draft: Dict[str, Any] = field("draft", doc="What the move was made with: ``name``, ``harness``, ``model``, "
                                               "``model_connection``.")
    source: Optional[Dict[str, Any]] = field(
        "source", doc="Where it moves from, as the moving agent says: ``harness``, ``host``, ``cwd``, "
                      "``cli_version``, ``session_id``, ``title``.")
    arrived: Dict[str, Any] = field(
        "arrived", doc="What arrived so far: ``session``, ``repo`` or ``checkout``, ``files``, ``consent``, "
                       "``secrets`` (names and where each goes), ``setup``, ``mcp_servers``, ``skills``, "
                       "``memories``, ``note``, ``instructions``, ``plan``, and once finished ``carried``; never a "
                       "value.")
    steps: List[Dict[str, Any]] = field(
        "steps", doc="The finish's progress, in order: each ``name`` (agent, space, files, tools, skills, memories, "
                     "conversation), ``label``, ``status`` (running, done, failed), ``detail``, and a failed "
                     "one's ``error`` and ``failure`` (the error whole: ``type``, ``message``, ``next_step``).")
    next_step: Optional[str] = field(
        "next_step", doc="What the moving agent does next while a finish runs (read the move again) or after one "
                         "failed (the failed step's own next step).")
    lands_as: Optional[Dict[str, Any]] = field(
        "lands_as", doc="Where it lands (on the moving side): the agent's ``name`` and ``harness``, ``cwd``, the "
                        "working directory its session moves to, and ``machine`` (``id``, ``name``), the machine it "
                        "runs on, or None for a sandbox of its own.")
    question: Optional[str] = field(
        "question", doc="What a finish asks before it makes anything (a session that carried no MCP server and no "
                        "skill: does it have none?).")
    endpoints: Optional[List[str]] = field(
        "endpoints", doc="The move's calls (on the moving side), one line each: method, path and what it does.")
    agent_id: Optional[str] = field("agent_id", doc="The agent it made, once done.")
    conversation: Optional[str] = field("conversation", doc="The agent's conversation holding the moved session.")
    error: Optional[str] = field("error", doc="Why it failed.")
    expires_at: Any = field("expires_at", parse_time, doc="When it ends if nobody finishes it.")
    created_at: Any = field("created_at", parse_time)

    async def _load(self) -> Dict[str, Any]:
        if self._known("id") is None:
            return await self._request("GET", "/v1/moves/current")
        return await self._request("GET", f"/v1/agents/moves/{self._known('id')}")

    # --- your side -------------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls, *, workspace: Any = None, name: Optional[str] = None, harness: Optional[str] = None,
        model: Optional[str] = None, model_connection: Any = None, machine: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "AgentMove":
        """Make a move: a one-time code, good once for 30 minutes, and the prompt a person pastes into the
        coding-agent session they want moved. The agent there follows the guide the prompt names, carries what
        its work needs, and finishes the move, which makes the agent.

        Args:
            workspace: The space (a ``Workspace`` or its id) the agent joins.
            name: Its name; omitted, the moving agent's choice, else its folder's.
            harness: ``claude_code``, ``codex``, ``opencode``, ``hermes`` or ``openclaw``; omitted, the session's own.
            model: Its model in the harness's format; omitted, the session's or the harness's default.
            model_connection: The connection holding its model's key or plan; omitted, the account's own that runs it.
            machine: The ``Machine`` (or id) it runs on, judged as placing an agent there is; omitted, a sandbox of
                its own. Its setup and secrets' files run in its container there as in a sandbox.

        Returns:
            The move, with ``code`` and ``prompt`` (only here).

        Usage::

            move = noclick.AgentMove.create(name="Docs fixer", harness="claude_code")
            print(move.prompt)
        """
        from .workspace import Workspace

        workspace_id = await ref_id(workspace) if isinstance(workspace, Workspace) else workspace
        connection = model_connection if model_connection is None or isinstance(model_connection, str) else (
            await ref_id(model_connection))
        body = compact(workspace_id=workspace_id, name=name, harness=harness, model=model,
                       model_connection=connection, machine_id=None if machine is None else await ref_id(machine))
        api = resolve_client(client)
        raw = await api.request("POST", "/v1/agents/moves", json=body, user=user)
        return cls._new(raw=raw, client=client, user=user)

    @classmethod
    def from_id(cls, move_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "AgentMove":
        """A lazy reference to a move by id.

        Returns:
            A move that loads the first time you read a field. Nothing is sent yet.

        Usage::

            move = noclick.AgentMove.from_id("8c1f3e2a-4b5d-4e6f-9a7b-0c1d2e3f4a5b")
            print(move.status)
        """
        return cls._new(hints={"id": move_id}, client=client, user=user)

    @synced
    async def cancel(self) -> "AgentMove":
        """Call the move off: its key stops working and what arrived goes. A finished move's agent stays.

        Returns:
            This move, ``canceled``.

        Usage::

            noclick.AgentMove.from_id("8c1f3e2a-4b5d-4e6f-9a7b-0c1d2e3f4a5b").cancel()
        """
        self._raw = await self._request("POST", f"/v1/agents/moves/{self._known('id')}/cancel")
        return self

    @synced
    async def connect_sign_in(self, name: str, credential: Any) -> "AgentMove":
        """Give a tool server the move carried needing sign-in the person's sign-in to it: the ``mcp_oauth``
        connection NoClick's own MCP sign-in made for its URL.

        Returns:
            This move, its ``carried`` entry for the server no longer needing sign-in.

        Usage::

            noclick.AgentMove.from_id("8c1f3e2a-4b5d-4e6f-9a7b-0c1d2e3f4a5b").connect_sign_in("notion", "cr_1")
        """
        credential_id = credential if isinstance(credential, str) else await ref_id(credential)
        self._raw = await self._request("POST", f"/v1/agents/moves/{self._known('id')}/sign_ins/{quote(name, safe='')}",
                                        json={"credential_id": credential_id})
        return self

    # --- the moving agent's side -----------------------------------------

    @staticmethod
    def redeem(code: str, *, host: Optional[str] = None, base_url: Optional[str] = None) -> str:
        """Redeem a move code for the move's own key, once. Keep it out of anything you print or save in your
        transcript: write it to a file only you read.

        Returns:
            The key: it reaches only this move, for an hour.

        Usage::

            key = noclick.AgentMove.redeem("nc_move_...", host="ana-mbp")
        """
        import os

        api_url = (base_url or os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
        response = httpx.post(f"{api_url}/v1/moves/redeem", data=compact(code=code, host=host), timeout=30)
        if response.status_code != 200:
            Client._decode(response)
        return response.text.strip()

    @synced
    @classmethod
    async def current(cls, *, client: Optional[Client] = None) -> "AgentMove":
        """The move the client's key belongs to (a move's own key, from ``redeem``).

        Returns:
            The move, with ``lands_as`` and the limits.

        Usage::

            moving = noclick.AgentMove.current(client=noclick.Client(api_key=key))
            print(moving.lands_as["cwd"])
        """
        api = resolve_client(client)
        return cls._new(raw=await api.request("GET", "/v1/moves/current", user=None), client=client, user=None)

    async def _moving(self, method: str, path: str, **kwargs: Any) -> "AgentMove":
        self._raw = await self._request(method, f"/v1/moves/current{path}", user=None, **kwargs)
        return self

    @synced
    async def set_source(self, *, harness: str, host: str, cwd: str, cli_version: Optional[str] = None,
                         session_id: Optional[str] = None, title: Optional[str] = None,
                         model: Optional[str] = None, effort: Optional[str] = None,
                         speed: Optional[str] = None) -> "AgentMove":
        """Say where the session moves from: its harness, machine and folder, and, where the session's own files don't
        record them, the model, effort (``"xhigh"``) and speed (``"fast"``) it runs at. What's said wins over what the
        session upload read; the rest of that stays.

        Returns:
            This move.

        Usage::

            moving.set_source(harness="claude_code", host="ana-mbp", cwd="/Users/ana/code/acme")
        """
        return await self._moving("PUT", "/source", json=compact(
            harness=harness, host=host, cwd=cwd, cli_version=cli_version, session_id=session_id, title=title,
            model=model, effort=effort, speed=speed))

    @synced
    async def upload_session(self, data: bytes, *, harness: str, cwd: str,
                             session_id: Optional[str] = None) -> "AgentMove":
        """The session's own files: a tar of paths relative to the harness's home (``~/.claude`` for Claude Code).

        Returns:
            This move; ``arrived["session"]`` says what NoClick read.

        Usage::

            moving.upload_session(tar_bytes, harness="claude_code", cwd="/Users/ana/code/acme", session_id=sid)
        """
        return await self._moving("PUT", "/session", content=data, params=compact(
            harness=harness, cwd=cwd, session_id=session_id))

    @synced
    async def repo(self, *, name: Optional[str] = None, branch: Optional[str] = None) -> Dict[str, Any]:
        """A NoClick repo for the code (made once) and a push ``url``, good for 10 minutes: treat it as a secret.

        Returns:
            ``repo_id``, ``name``, ``branch``, ``path``, ``url``, ``expires_at`` and ``cwd``.

        Usage::

            pushed = moving.repo()
            # git push <pushed["url"]> HEAD:refs/heads/<pushed["branch"]>
        """
        return await self._request("POST", "/v1/moves/current/repo", json=compact(name=name, branch=branch),
                                   user=None)

    @synced
    async def put_file(self, path: str, data: bytes) -> "AgentMove":
        """A file from outside the repo, placed at ``/workspace/<path>`` (up to 100 MB).

        Returns:
            This move.

        Usage::

            moving.put_file("notes/spec.md", open("/Users/ana/notes/spec.md", "rb").read())
        """
        return await self._moving("PUT", "/files", content=data, params={"path": path})

    @synced
    async def consent(self, secrets: List[Mapping[str, str]], *, confirmed: bool) -> "AgentMove":
        """The secrets the person said yes to carrying, each ``{name, kind, to}`` (what it is and where it goes, as
        they read it; never a value). ``confirmed=True`` once they said yes in the session. A secret is carried only
        once it's listed here; this replaces the list sent before.

        Returns:
            This move; ``arrived["consent"]`` lists them.

        Usage::

            moving.consent([{"name": "linear-token", "kind": "Linear API key", "to": "env LINEAR_API_KEY"}],
                           confirmed=True)
        """
        return await self._moving("PUT", "/consent", json={"secrets": [dict(s) for s in secrets],
                                                           "confirmed": confirmed})

    @synced
    async def put_secret(self, name: str, value: str, *, to: Optional[Mapping[str, Any]] = None) -> "AgentMove":
        """One secret the session uses, sealed as it lands, and where it goes in the copy: ``{"env": NAME}``,
        ``{"file": path, "mode": "600"}``, ``{"model": provider}`` (the model key it runs on), or none for one a tool
        server's header or the checkout refers to by name.

        Returns:
            This move; ``arrived["secrets"]`` names it, never its value.

        Usage::

            moving.put_secret("linear-token", os.environ["LINEAR_API_KEY"], to={"env": "LINEAR_API_KEY"})
        """
        return await self._moving("PUT", f"/secrets/{quote(name, safe='')}",
                                  json={"value": value, "to": dict(to or {})})

    @synced
    async def set_setup(self, commands: List[str]) -> "AgentMove":
        """What the copy's sandbox runs as it starts (after its secrets' files are written): the CLIs and packages
        the session used.

        Returns:
            This move.

        Usage::

            moving.set_setup(["npm install -g @linear/cli"])
        """
        return await self._moving("PUT", "/setup", json={"commands": list(commands)})

    @synced
    async def set_checkout(self, url: str, branch: str, *, path: Optional[str] = None, secret: Optional[str] = None,
                           username: Optional[str] = None) -> "AgentMove":
        """The session's own git remote (an https URL), checked out in the copy at ``branch`` (where the session
        pushed its work), signed in with the carried secret ``secret``'s value when it must be.

        Returns:
            This move; ``lands_as["cwd"]`` is where it's checked out.

        Usage::

            moving.set_checkout("https://github.com/acme/web.git", "noclick/ana-mbp", secret="github-token")
        """
        return await self._moving("PUT", "/checkout", json=compact(url=url, branch=branch, path=path, secret=secret,
                                                                 username=username))

    @synced
    async def plan_link(self) -> Dict[str, Any]:
        """The one-tap sign-in to the plan the session's harness runs on (Claude's, ChatGPT's), for the person: its
        tokens never move. Once they sign in, the copy runs on it.

        Returns:
            ``{connection, integration, status, url, expires_at}``.

        Usage::

            print(moving.plan_link()["url"])
        """
        return await self._request("POST", "/v1/moves/current/plan_link", user=None)

    @synced
    async def add_mcp_server(self, name: str, url: str, *, transport: str = "http",
                             headers: Optional[Mapping[str, Any]] = None,
                             sign_in: Optional[str] = None) -> "AgentMove":
        """A remote MCP server it used (a public https URL); the agent gets its tools. A header's value is text,
        or ``{"secret": name}`` for a carried secret's (a login written as text is refused).

        Args:
            sign_in: ``"browser"`` for a server whose login lives in a browser (a claude.ai connector, an OAuth
                sign-in): it moves with no headers and no login, and the person signs in to it once on NoClick.

        Returns:
            This move.

        Usage::

            moving.add_mcp_server("deepwiki", "https://mcp.deepwiki.com/mcp")
            moving.add_mcp_server("notion", "https://mcp.notion.com/mcp", sign_in="browser")
        """
        return await self._moving("PUT", f"/mcp_servers/{quote(name, safe='')}", json=compact(
            url=url, transport=transport, headers=dict(headers or {}), sign_in=sign_in))

    @synced
    async def add_skill(self, name: str, data: bytes) -> "AgentMove":
        """A skill: its folder as a tar, SKILL.md at its top.

        Returns:
            This move.

        Usage::

            moving.add_skill("release-notes", tar_bytes)
        """
        return await self._moving("PUT", f"/skills/{quote(name, safe='')}", content=data)

    @synced
    async def add_memory(self, name: str, content: str, *, description: str) -> "AgentMove":
        """Something it learned, kept in its NoClick memory.

        Returns:
            This move.

        Usage::

            moving.add_memory("deploy-steps", "Deploy with make ship.", description="How this repo deploys")
        """
        return await self._moving("PUT", f"/memories/{quote(name, safe='')}",
                                  json={"content": content, "description": description})

    @synced
    async def set_note(self, text: str) -> "AgentMove":
        """The handoff note: what it's in the middle of and what's next. The agent reads it first.

        Returns:
            This move.

        Usage::

            moving.set_note("Halfway through the retry fix; next, a test for the third retry.")
        """
        return await self._moving("PUT", "/note", content=text.encode())

    @synced
    async def set_instructions(self, text: str) -> "AgentMove":
        """Its instructions: what it was told for every project (a user-level CLAUDE.md or AGENTS.md).

        Returns:
            This move.

        Usage::

            moving.set_instructions(open(os.path.expanduser("~/.claude/CLAUDE.md")).read())
        """
        return await self._moving("PUT", "/instructions", content=text.encode())

    @synced
    async def finish(self, *, name: Optional[str] = None, model: Optional[str] = None,
                     model_connection: Optional[str] = None, harness: Optional[str] = None,
                     none: Optional[Sequence[str]] = None, wait: bool = True) -> "AgentMove":
        """Make the agent from what arrived. NoClick runs the finish's steps (``finishing``) and this reads the move
        until they end; the move's key ends a few minutes after. Finish again after a failed step to pick up there.

        Args:
            harness: The harness it runs on, when the Draft screen named none (a carried key the session's own
                harness doesn't run on is refused naming the ones it does).
            model: Its model, in that harness's format, when the Draft screen named none.
            none: What the session has none of (``mcp_servers``, ``skills``), said outright: a finish that carried
                neither asks first (``question``).
            wait: Read the move until the finish ends (the default); False returns it ``finishing``.

        Returns:
            This move: ``done``, with ``agent_id`` and ``conversation``; ``finishing`` with ``wait=False``; or still
            ``moving`` with a ``question``.

        Raises:
            The failed step's error (``Conflict``, ``InvalidRequest``...), its ``next_step`` saying what to do.

        Usage::

            moving.finish()
            moving.finish(harness="opencode", model="openrouter/anthropic/claude-sonnet-4.5")
        """
        await self._moving("POST", "/finish", json=compact(
            name=name, model=model, model_connection=model_connection, harness=harness,
            none=None if none is None else list(none)))
        while wait and self.status == "finishing":
            await self._api._sleep(FINISH_POLL_S)
            await self._moving("GET", "")
        if wait and self.status == "failed":
            failed = next((s for s in self.steps or [] if s["status"] == "failed"), {})
            raise error_from_payload(failed.get("failure") or {"message": self.error, "next_step": self.next_step},
                                     default=OperationFailed)
        return self
