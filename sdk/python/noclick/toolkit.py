"""Toolkits: your connections' operations, the operations that need no account,
and capabilities as LLM tools.

    gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True)
    toolkit = noclick.Toolkit(["search", gmail])
    response = anthropic.messages.create(..., tools=toolkit.definitions())
    messages.append({"role": "user", "content": toolkit.handle(response)})

A call never raises for something the model can act on: a missing connection,
a policy refusal or a hold for approval comes back as an ``is_error`` result.
A hold's ``approval_required`` (``approval_id``, ``request_id``, ``approve_url``,
``operation``, ``approver``) is never shown to the model; pass ``on_approval=``
to the ``handle`` helpers to receive it, and ``on_connect=`` to receive each
result that needs a connection. ``request_id`` (the request a person answers),
``approve_url`` and ``operation`` (the approval's operation object) are ``None``
unless the request is addressed to you; the approver is emailed either way.
Once the person approves, the identical call goes through.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from dataclasses import dataclass, field as dc_field, replace
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple, Union

from ._client import Client, resolve_client
from ._sync import synced
from ._scope import AMBIENT, resolve_scope
from .connection import Connection, ConnectionOperations, tool_refs
from .database import Database, DatabaseOperations
from .human import HumanRequest
from .mcp_server import McpServer


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one tool call. An unconnected account is a normal result
    whose ``needs_connection`` names the ``connection``, its ``integration``
    and the ``connect_url`` to send the user;
    a call held for approval carries ``approval_required``: ``approval_id``,
    ``request_id``, ``approve_url``, ``operation`` and ``approver`` (``"user"``
    or ``"owner"``). ``request_id`` (the request a person answers),
    ``approve_url`` and ``operation`` (the approval's operation object) are
    ``None`` unless the request is addressed to you; the approver is emailed
    either way."""

    name: str
    content: Any
    is_error: bool
    needs_connection: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)
    approval_required: Optional[Dict[str, Any]] = None
    #: The arguments the call was made with, as the model gave them.
    arguments: Optional[Dict[str, Any]] = None
    #: The model's id for the call (its ``tool_use`` or tool call id) when it came through ``handle``
    #: or ``handle_openai``; None from ``call``.
    call_id: Optional[str] = None
    _client: Optional[Client] = dc_field(default=None, repr=False, compare=False)
    _scope: Any = dc_field(default=None, repr=False, compare=False)

    @property
    def connect_url(self) -> Optional[str]:
        return (self.needs_connection or {}).get("connect_url")

    @property
    def approval(self) -> Optional[HumanRequest]:
        """The approval a held call waits on, as a request: ``wait()`` gives ``True`` once
        approved. ``None`` unless the call was held and the request is addressed to you."""
        return HumanRequest._held(self.approval_required or {}, client=self._client, user=self._scope)

    @property
    def approve_url(self) -> Optional[str]:
        """The approval link, when the call waits for your approval; once
        approved, repeat the identical call."""
        return (self.approval_required or {}).get("approve_url")

    @property
    def text(self) -> str:
        """The content as one string (what an OpenAI tool message carries)."""
        return _as_text(self.content)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and all(_get(b, "type") == "text" for b in content):
        return "\n".join(_get(b, "text") or "" for b in content)
    return json.dumps(content, default=str)


def _as_anthropic_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(b, dict) and "type" in b for b in content):
        return content
    return json.dumps(content, default=str)


def _tool_ref(ref: Any) -> Any:
    if isinstance(ref, (str, Connection, ConnectionOperations, Database)) or hasattr(ref, "_tool_refs"):
        return ref
    raise TypeError(
        f"Toolkit tools are Connections, Databases or names like 'gmail' or 'gmail.send_email_message', not {ref!r}"
    )


def _anthropic_tool_uses(content: Any) -> List[Tuple[str, str, Dict[str, Any]]]:
    """``(id, name, input)`` for each ``tool_use`` block in a Message, a
    message dict, or a list of blocks (SDK objects or dicts)."""
    if not isinstance(content, (list, tuple, dict)) and _get(content, "type") != "tool_use":
        content = _get(content, "content", content)
    elif isinstance(content, dict) and content.get("type") != "tool_use" and "content" in content:
        content = content["content"]
    if isinstance(content, dict) or _get(content, "type") == "tool_use":
        content = [content]
    uses = []
    for block in content or []:
        if _get(block, "type") == "tool_use":
            uses.append((_get(block, "id"), _get(block, "name"), _get(block, "input") or {}))
    return uses


def _openai_tool_calls(calls: Any) -> List[Tuple[str, str, Any, str]]:
    """``(id, name, raw_arguments, shape)`` from a ChatCompletion, a message,
    a list of tool calls, or Responses ``function_call`` items."""
    if _get(calls, "choices") is not None:
        calls = _get(_get(calls, "choices")[0], "message")
    if not isinstance(calls, (list, tuple)):
        for attr in ("tool_calls", "output"):
            inner = _get(calls, attr)
            if isinstance(inner, (list, tuple)):
                calls = inner
                break
        else:
            calls = [calls]
    found = []
    for call in calls:
        if _get(call, "type") == "function_call":
            found.append((_get(call, "call_id"), _get(call, "name"), _get(call, "arguments"), "responses"))
        elif _get(call, "function") is not None:
            fn = _get(call, "function")
            found.append((_get(call, "id"), _get(fn, "name"), _get(fn, "arguments"), "chat"))
    return found


OnApproval = Callable[[ToolResult], Optional[Awaitable[None]]]
OnConnect = Callable[[ToolResult], Optional[Awaitable[None]]]


async def _report(results: List[ToolResult], on_approval: Optional[OnApproval], on_connect: Optional[OnConnect]) -> None:
    """Each held call to ``on_approval`` and each call that needs a connection to ``on_connect``, in call order."""
    for result in results:
        for wanted, callback in ((result.approval_required, on_approval), (result.needs_connection, on_connect)):
            if wanted and callback is not None:
                outcome = callback(result)
                if inspect.isawaitable(outcome):
                    await outcome


class Toolkit:
    """A set of tools for your LLM. Entries are connections (a ``Connection``
    or its name: every operation, as ``{connection}__{operation}`` tools),
    single operations (``"gmail.send_email_message"``), capabilities
    (``"search"``, ``"fetch"``, ``"code"``) or a ``Database`` (``{database}__query``,
    ``__execute`` and ``__schema``; invite-only beta), a ``Bucket`` and
    operations with arguments bound (``gmail.only("send_email_message").bind(to=...)``:
    the bound parameters leave the tool's schema and are filled on every call, so a
    toolkit sends its entries with each call). A name resolves in the
    user the calls act for (``user=`` if given, else the user current at each call,
    ``as_user``): a connection there, else an integration's operations that need no account
    (on NoClick's key), so ``"exa.search"`` needs no connection. A ``Connection`` object from
    another scope, another user's or your account's, stays that connection (a key acting for the whole
    account only).

    Usage:
        Build one toolkit at module level and use it for every user: ``"gmail"`` is
        each user's own connection named gmail, and ``"exa.search"`` needs none::

            toolkit = noclick.Toolkit(["gmail", "slack.send_message_to_channel", "exa.search"])
            print(toolkit.tools)

        Or pin it to one user, with only some of a connection's operations::

            gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True, user="user_42")
            toolkit = noclick.Toolkit([gmail.only("send_email_message"), "fetch"], user="user_42")

        To test your loop without touching anyone's accounts, let a simulated world answer
        every call. The definitions are the real ones; the toolkit is one world, so what one
        call creates the next one finds, for 30 minutes after its last call, and each answer
        is billed as AI at NoClick's model price, as a test run's world is::

            toolkit = noclick.Toolkit(["gmail", "stripe"], simulated=True, scenario="Ana has two unpaid invoices")
            result = toolkit.call("stripe__list_invoices", {"status": "open"}, user="user_42")
            print(result.text)   # made up, consistent with the scenario; nothing was read or sent
    """

    def __init__(
        self,
        tools: Union[str, Iterable[Any]],
        *,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
        simulated: bool = False,
        scenario: Optional[str] = None,
    ) -> None:
        entries = [tools] if isinstance(tools, (str, Connection, Database)) else list(tools)
        #: What was passed: names, ``"name.operation"`` strings and ``Connection`` objects.
        self.refs: List[Any] = [_tool_ref(ref) for ref in entries]
        self._scope = user
        self._client = client
        self._definitions: Dict[str, List[Dict[str, Any]]] = {}
        #: Whether a simulated world answers every call instead of the real accounts.
        self.simulated = simulated
        if scenario is not None and not simulated:
            raise ValueError("A scenario describes the simulated world; pass simulated=True with it.")
        #: What that world is like; its answers keep to it.
        self.scenario = scenario
        # One toolkit is one world: what a call creates, later calls see.
        self._world = f"world_{uuid.uuid4().hex}" if simulated else None

    @property
    def tools(self) -> List[str]:
        """The refs as names (a Connection known only by id shows its id until used)."""
        names: List[str] = []
        for ref in self.refs:
            if isinstance(ref, str):
                names.append(ref)
            elif isinstance(ref, ConnectionOperations):
                base = ref.connection._known("name") or ref.connection._known("id")
                names.extend(f"{base}.{op}" for op in ref.operations)
            elif isinstance(ref, DatabaseOperations):
                base = ref.database._known("name") or ref.database._known("id")
                names.extend(f"{base}.{op}" for op in ref.operations)
            elif hasattr(ref, "bucket") and hasattr(ref, "operations"):  # bucket.only(...)
                base = ref.bucket._known("name") or ref.bucket._known("id")
                names.extend(f"{base}.{op}" for op in ref.operations)
            elif hasattr(ref, "_known"):
                names.append(ref._known("name") or ref._known("id"))
            else:
                names.append(repr(ref))
        return names

    def __repr__(self) -> str:
        return f"Toolkit({self.tools!r}{', simulated=True' if self.simulated else ''})"

    def mcp_server(self, name: str) -> McpServer:
        """These tools as a hosted MCP server called ``name``, in the toolkit's
        user (``McpServer.from_name`` with ``create_if_missing=True``). Sends nothing yet.

        Returns:
            The server, created on first use (or, when it exists, given this toolkit's tools); its ``url``
            is what you give an MCP client.

        Usage::

            toolkit = noclick.Toolkit(["hubspot", "search"], user="acme")
            server = toolkit.mcp_server("crm-tools")
            print(server.url)
        """
        if self.simulated:
            raise ValueError("A hosted MCP server calls the real accounts; build it from a toolkit without simulated=True.")
        return McpServer.from_name(name, tools=self.refs, create_if_missing=True, user=self._scope, client=self._client)

    async def _request(self, path: str, body: Dict[str, Any], user: Any) -> Any:
        scope = self._scope if user is AMBIENT else user
        return await resolve_client(self._client).request("POST", path, json=body, user=scope)

    async def _refs(self, user: Any) -> Optional[List[Any]]:
        """The wire refs for the user a call acts for (a connection from another scope goes by id)."""
        return await tool_refs(self.refs, scope=self._scope if user is AMBIENT else user)

    @synced
    async def definitions(self, format: str = "anthropic", *, user: Any = AMBIENT) -> List[Dict[str, Any]]:
        """Describe the toolkit's tools for your LLM API
        (``format`` = ``"anthropic"``, ``"openai"`` or ``"mcp"``). Cached per format.

        Returns:
            The tool definitions in that API's shape, ready to pass as ``tools``. The first call for a
            format fetches them; later calls reuse them.

        Usage:
            For Claude, the default format::

                toolkit = noclick.Toolkit(["gmail", "search"])
                with noclick.as_user("user_42"):
                    tools = toolkit.definitions()
                print([tool["name"] for tool in tools])   # ['gmail__send_email_message', ..., 'search']

            For OpenAI, or for an MCP server of your own::

                toolkit = noclick.Toolkit(["gmail", "search"])
                openai_tools = toolkit.definitions("openai", user="user_42")
                mcp_tools = toolkit.definitions("mcp", user="user_42")
        """
        if format not in self._definitions:
            refs = await self._refs(user)
            response = await self._request("/v1/toolkits/definitions", {"tools": refs, "format": format}, user)
            self._definitions[format] = list((response or {}).get("tools") or [])
        return self._definitions[format]

    @synced
    async def call(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        approval_id: Optional[str] = None,
        user: Any = AMBIENT,
    ) -> ToolResult:
        """Run one tool by its wire name (``gmail__send_email_message`` for the
        connection named gmail, ``search``).
        A policy refusal or a hold is an ``is_error`` result, never an
        exception; a held call goes through once approved when it is repeated
        with the same arguments (``approval_id=`` names the approval explicitly).

        Returns:
            The tool's ``content`` (``text`` as one string) and whether it ``is_error``. A call that couldn't
            run says why in ``content``, with ``needs_connection`` or ``approval_required`` set when that's the reason.

        Usage:
            Run a tool by the name the model uses::

                toolkit = noclick.Toolkit(["gmail", "search"])
                result = toolkit.call("gmail__fetch_emails_from_inbox", {"max_results": 5}, user="user_42")
                print(result.is_error, result.text)

            When the user hasn't connected the account yet, the result carries the link to send them::

                toolkit = noclick.Toolkit(["gmail"])
                result = toolkit.call("gmail__fetch_emails_from_inbox", {"max_results": 5}, user="user_42")
                if result.needs_connection:
                    print(result.connect_url)
        """
        request: Dict[str, Any] = {"name": name, "arguments": arguments or {}}
        if any(not isinstance(ref, (str, Database)) for ref in self.refs):
            # A name resolves among the acting user's; a connection from another scope, and bound
            # arguments or a person, need their refs.
            refs = await self._refs(user) or []
            if any(not isinstance(ref, str) or ref.startswith("connection:") for ref in refs):
                request["tools"] = refs
        if approval_id is not None:
            request["approval_id"] = approval_id
        if self.simulated:
            request["simulated"] = {"world": self._world, **({"scenario": self.scenario} if self.scenario else {})}
        raw = await self._request("/v1/toolkits/call", request, user) or {}
        return ToolResult(
            name=raw.get("name", name),
            content=raw.get("content"),
            is_error=bool(raw.get("is_error")),
            needs_connection=raw.get("needs_connection"),
            raw=raw,
            approval_required=raw.get("approval_required"),
            arguments=dict(arguments or {}),
            _client=self._client,
            _scope=resolve_scope(self._scope if user is AMBIENT else user),
        )

    @synced
    async def handle(
        self,
        content: Any,
        *,
        user: Any = AMBIENT,
        on_approval: Optional[OnApproval] = None,
        on_connect: Optional[OnConnect] = None,
    ) -> List[Dict[str, Any]]:
        """Run every Anthropic ``tool_use`` block (from a ``Message``, its
        ``content`` list, or dicts) concurrently. A tool your policy
        denies or holds for approval comes back as an error result;
        ``on_approval(result)`` (sync or async) receives each held call's
        ``ToolResult``, in call order, and ``on_connect(result)`` each one whose
        ``needs_connection`` is set, so your app can show the user the connect link
        instead of relying on the model to pass it on. Each result carries the
        model's ``call_id`` and the ``arguments``.

        Returns:
            One ``tool_result`` block per ``tool_use``, in order: the ``content`` of the next user turn.

        Usage:
            Run the model loop with Claude::

                import anthropic

                claude = anthropic.Anthropic()
                toolkit = noclick.Toolkit(["gmail", "search"])
                messages = [{"role": "user", "content": "Email Ana the notes from today's standup"}]
                with noclick.as_user("user_42"):
                    while True:
                        response = claude.messages.create(
                            model="claude-sonnet-5", max_tokens=1024, tools=toolkit.definitions(), messages=messages,
                        )
                        if response.stop_reason != "tool_use":
                            break
                        messages.append({"role": "assistant", "content": response.content})
                        messages.append({"role": "user", "content": toolkit.handle(response)})

            The model never sees who approves a held call or the approval link. Pass ``on_approval`` to get them::

                toolkit = noclick.Toolkit(["gmail"])
                blocks = toolkit.handle(response, on_approval=lambda result: notify_approver(result.approval_required))

            Show the user a Connect button when a tool needs their account::

                toolkit = noclick.Toolkit(["gmail", "google_calendar"])
                blocks = toolkit.handle(
                    response, user="user_42",
                    on_connect=lambda result: show_connect_button(result.needs_connection["integration"], result.connect_url),
                )
        """
        uses = _anthropic_tool_uses(content)
        results = [
            replace(result, call_id=use_id)
            for (use_id, _, _), result in zip(
                uses, await asyncio.gather(*(self.call.aio(name, args, user=user) for _, name, args in uses)),
            )
        ]
        await _report(results, on_approval, on_connect)
        return [
            {
                "type": "tool_result",
                "tool_use_id": use_id,
                "content": _as_anthropic_content(result.content),
                "is_error": result.is_error,
            }
            for (use_id, _, _), result in zip(uses, results)
        ]

    @synced
    async def handle_openai(
        self,
        tool_calls: Any,
        *,
        user: Any = AMBIENT,
        on_approval: Optional[OnApproval] = None,
        on_connect: Optional[OnConnect] = None,
    ) -> List[Dict[str, Any]]:
        """Run OpenAI tool calls (a ChatCompletion, its message, a
        ``tool_calls`` list, or Responses ``function_call`` items).
        ``on_approval`` and ``on_connect`` work as in ``handle``.

        Returns:
            One ``{"role": "tool"}`` message per call, in order, or a ``function_call_output`` item for each
            Responses call. A call whose arguments aren't valid JSON isn't run; its message tells the model so.

        Usage::

            from openai import OpenAI

            gpt = OpenAI()
            toolkit = noclick.Toolkit(["gmail", "search"])
            messages = [{"role": "user", "content": "Summarize the emails Ana sent me this week"}]
            with noclick.as_user("user_42"):
                while True:
                    completion = gpt.chat.completions.create(
                        model="gpt-5.1", tools=toolkit.definitions("openai"), messages=messages,
                    )
                    message = completion.choices[0].message
                    if not message.tool_calls:
                        break
                    messages.append(message)
                    messages += toolkit.handle_openai(completion)
        """
        calls = _openai_tool_calls(tool_calls)

        async def _run(call_id: str, name: str, arguments: Any) -> Union[str, ToolResult]:
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments) if arguments.strip() else {}
                except ValueError:
                    return f"The arguments for {name} were not valid JSON: {arguments[:200]}"
            return replace(await self.call.aio(name, arguments or {}, user=user), call_id=call_id)

        outputs = await asyncio.gather(*(_run(call_id, name, args) for call_id, name, args, _ in calls))
        await _report([o for o in outputs if isinstance(o, ToolResult)], on_approval, on_connect)
        messages: List[Dict[str, Any]] = []
        for (call_id, _, _, shape), output in zip(calls, outputs):
            text = output.text if isinstance(output, ToolResult) else output
            if shape == "responses":
                messages.append({"type": "function_call_output", "call_id": call_id, "output": text})
            else:
                messages.append({"role": "tool", "tool_call_id": call_id, "content": text})
        return messages
