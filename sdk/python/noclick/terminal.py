"""Take-over: the account's owner drives a coding agent's conversation in its harness's own terminal (Claude Code's
or Codex's), then hands it back, and the agent's next turn goes on from what they did.

``agent.take_over(conversation)`` returns a ``Terminal`` whose ``url`` and single-use ``token`` open it: a websocket
whose first message is ``{"type": "auth", "token": ..., "cols": ..., "rows": ...}``; then binary messages carry
what the person types and what the terminal prints, a text ``{"type": "resize", "cols", "rows"}`` sizes it, and the
server sends ``{"type": "ready"}`` once and ``{"type": "state", ...}`` as the take-over moves, closing with code 4410
once the agent has the conversation again. Hand the ``url`` and ``token`` to your user's browser (xterm.js, or the
TypeScript SDK's ``Terminal.connect``) from your server: a terminal needs the account's secret key with the
``agents:terminal`` scope, never a user's session.

    coder = noclick.Agent.from_name("coder")
    terminal = coder.take_over("main", interrupt=True)
    send_to_browser(terminal.url, terminal.token)   # within two minutes
    ...
    terminal.hand_back()
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from ._object import _Object, field, parse_time
from ._sync import synced

TERMINAL_STATES = ("agent", "taking_over", "person", "handing_back")


class Terminal(_Object):
    """A coding agent's conversation as its harness's own terminal: ``state`` is ``agent`` (the agent has it),
    ``taking_over`` (its turn in flight finishes first), ``person`` (taken over) or ``handing_back``. While it's
    taken over the agent's messages wait; it hands itself back after ``idle_limit_s`` with nobody typing,
    ``detached_limit_s`` with no terminal open, or at ``ends_at`` (its sandbox's time limit)."""

    _repr_keys = ("agent_id", "conversation", "state")

    agent_id: str = field("agent_id")
    conversation: str = field("conversation")
    harness: str = field("harness", doc="``claude_code`` or ``codex``.")
    state: str = field("state", doc="``agent``, ``taking_over``, ``person`` or ``handing_back``.")
    waiting_for_turn: bool = field("waiting_for_turn", doc="Taken over once the agent's turn in flight ends.")
    since: Any = field("since", parse_time, doc="When it was taken over.")
    ends_at: Any = field("ends_at", parse_time, doc="When it hands itself back at the latest: its sandbox's limit.")
    idle_limit_s: Optional[int] = field("idle_limit_s", doc="It hands itself back after this long with nobody typing.")
    detached_limit_s: Optional[int] = field(
        "detached_limit_s", doc="It hands itself back after this long with no terminal open.")
    ended_because: Optional[str] = field(
        "ended_because",
        doc="Why the last take-over ended: ``handed_back``, ``canceled``, ``idle``, ``detached``, ``exited`` (the "
        "terminal's program exited), ``deadline`` or ``failed``.")
    url: Optional[str] = field("url", doc="The terminal's websocket (from ``take_over`` only).")
    token: Optional[str] = field(
        "token", doc="Opens ``url`` once, within two minutes (from ``take_over`` only): its first message's ``token``.")
    token_expires_at: Any = field("token_expires_at", parse_time)

    @classmethod
    def _of(cls, raw: Dict[str, Any], *, client: Any, user: Any) -> "Terminal":
        return cls._new(raw=raw, client=client, user=user)

    def _path(self) -> str:
        return (f"/v1/agents/{self._known('agent_id')}/conversations/"
                f"{quote(str(self._known('conversation')), safe='')}/terminal")

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    @synced
    async def hand_back(self) -> "Terminal":
        """Give the conversation back to the agent: the terminal closes, what was said in it joins the
        conversation's history (``via: "terminal"``), and the messages that waited reach the agent.

        Returns:
            This terminal, as it is now (``agent``, or ``handing_back`` while its program exits).

        Usage::

            coder = noclick.Agent.from_name("coder")
            coder.terminal("main").hand_back()
        """
        self._raw = await self._request("DELETE", self._path())
        return self
