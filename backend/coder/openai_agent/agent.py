"""OpenAI Agents SDK wrapper for workflow and interactive-chat agents.

Provides multi-provider model dispatch, optional workspace command execution,
Postgres-backed conversation sessions, tool-call auditing, and deterministic
resource cleanup behind the shared ``Agent`` interface.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

import contextlib
import json

from agents import Agent as SDKAgent, ModelSettings, Runner
from agents.extensions.models.litellm_model import LitellmModel  # noqa: F401 — re-exported for callers

from .litellm_model import CostCapturingLitellmModel
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from agents.tool import FunctionTool

from wss.sender import AgentStateEvent, ChatMessageEvent
from wss.sender.schema import ContentItem, ImageUrl

from .billing import BillingHooks, InsufficientBalanceError, build_litellm_env
from .config import AgentConfiguration, LLMConfig
from .output_limits import clip_bash_result
from .sandbox import create_sandbox_runtime
from .session import PostgresSession
from utils.thread_env import override_env

logger = logging.getLogger(__name__)

# Cap on model turns (tool-call round-trips) in one agent run. The SDK Runner
# defaults to 10, which cut off multi-step tasks mid-work ("Max turns (10)
# exceeded"); 30 gives room for a real chain of tool calls without letting a
# runaway loop bill unbounded.
AGENT_MAX_TURNS = 30

# ── Transient-error retry for the streamed agent turn ────────────────────────
# Providers fail mid-stream (observed: OpenRouter relaying a MiniMax inference
# error as finish_reason='error' before any token), which previously killed
# unattended runs outright. A turn is retried ONLY when the failed attempt
# produced nothing observable — no streamed text and no run items (tool
# calls!) — so a retry can never duplicate user-visible output or re-fire a
# side effect. Deterministic 4xx-class errors (auth, bad request, content
# policy, context window) are excluded: retrying those just burns time.
_LLM_RUN_ATTEMPTS = 3
_RETRY_BASE_DELAY_S = 1.0
_RETRY_MAX_DELAY_S = 8.0


def _apply_exacto_variant(model: str) -> str:
    """Route a user-selected OpenRouter model through OpenRouter's ``:exacto`` variant,
    which pins the request to providers vetted for tool-calling accuracy — agents lean
    heavily on tool calls, so this is the routing we want by default. Applied to the SDK
    model ONLY; ``config.llm.model`` keeps the user's base id, so billing/usage records
    and cost lookups stay keyed to the base (the real cost still comes from OpenRouter's
    per-call header). No-op for non-OpenRouter models and for ids that already carry a
    variant suffix (``:free``/``:nitro``/``:exacto``/…) the user chose deliberately."""
    if not model or not model.startswith("openrouter/"):
        return model
    slug = model[len("openrouter/"):]
    if ":" in slug:  # already has an explicit variant — respect it
        return model
    return f"{model}:exacto"


def _build_model_settings(
    model: str, temperature: Optional[float], *, rehearsing: bool = False
) -> ModelSettings:
    """Model settings for ``model`` — shared by construction and update_model.

    - include_usage=True triggers stream_options.include_usage so providers
      emit a usage chunk with token counts in the stream (standard, all
      providers).
    - extra_body={"usage": {"include": True}} is OpenRouter's custom extension
      that adds an exact ``cost`` field to that usage chunk (visible at
      https://openrouter.ai/activity); CostCapturingLitellmModel's stream
      interceptor reads it off the chunks before the SDK transforms the
      response (see litellm_model.py). OpenRouter ONLY: litellm merges
      extra_body verbatim into the outbound JSON, and strict providers reject
      unknown properties — Groq 400s with ``property 'usage' is unsupported``,
      Anthropic rejects the literal ``extra_body`` key. Gate on the ORIGINAL
      model string: the Zen gateway rewrites ``opencode/*`` to ``openai/…``
      before the request, but settings are decided here, pre-rewrite.
    - ``rehearsing``: the Test Run trace shows thought rows between tool
      calls, but most models emit NO reasoning unless asked — a rehearsal
      without this renders an empty thought chain (2026-08-10). OpenRouter's
      unified reasoning param, riding inside the same openrouter/ gate (the
      Groq lesson applies to it too). Rehearsals only — production turns keep
      their tuned latency/cost profile.
    """
    if not model.startswith("openrouter/"):
        return ModelSettings(temperature=temperature, include_usage=True)
    extra_body: Dict[str, Any] = {"usage": {"include": True}}
    if rehearsing:
        extra_body["reasoning"] = {"effort": "low"}
    return ModelSettings(
        temperature=temperature, include_usage=True, extra_body=extra_body
    )


def _build_sdk_model(model: str, env: Optional[Dict[str, str]]) -> CostCapturingLitellmModel:
    """Construct the LiteLLM-backed SDK model for ``model``.

    OpenCode Zen/Go models (``opencode/*`` / ``opencode-go/*``) have no native
    LiteLLM provider, so they route via LiteLLM's ``openai/`` provider against
    the tier's gateway with the key passed EXPLICITLY — inline params beat env
    lookups, so LiteLLM can never fall back to the platform ``OPENAI_API_KEY``
    and send it to opencode.ai. A missing key fails here, before any streaming
    work, with the same message the CLI pre-flight gate uses. Every other model
    keeps LiteLLM's native routing (+ the OpenRouter ``:exacto`` variant)."""
    from nodes.agent.config.providers import (
        resolve_zen_gateway_route,
        validate_provider_credentials,
    )

    route = resolve_zen_gateway_route(model)
    if route is None:
        return CostCapturingLitellmModel(model=_apply_exacto_variant(model))
    validate_provider_credentials(model, env)
    return CostCapturingLitellmModel(
        model=route.litellm_model,
        base_url=route.base_url,
        api_key=(env or {})[route.api_key_env],
    )


def _is_retryable_llm_error(exc: BaseException) -> bool:
    import litellm

    return isinstance(exc, (
        litellm.APIConnectionError,  # includes mid-stream provider drops
        litellm.InternalServerError,
        litellm.RateLimitError,
        litellm.ServiceUnavailableError,
        litellm.Timeout,
    ))


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with full jitter (attempt is 0-based)."""
    return random.uniform(0.0, min(_RETRY_MAX_DELAY_S, _RETRY_BASE_DELAY_S * (2 ** attempt)))


class Agent:
    """OpenAI-Agents-SDK-backed agent.

    Public surface: ``Agent.create(...)``, ``await agent(message)``,
    ``await agent.cleanup()``. Plus chat-handler conveniences:
    ``set_working_directory``, ``pause``, ``update_model``, and the
    ``.model`` / ``.env`` read-only properties.
    """

    def __init__(
        self,
        emit_message: Callable[..., Awaitable[None]],
        config: AgentConfiguration,
        conversation_id: Optional[str] = None,
        sid: Optional[str] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        sio: Optional[Any] = None,
        env: Optional[Dict[str, str]] = None,
        enable_persistence: bool = True,
        custom_tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        organization_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        node_id: Optional[str] = None,
        filesystem_configs: Optional[List[Dict[str, Any]]] = None,
        conversation_key: Optional[str] = None,
        sandbox_setups: Optional[List[Dict[str, Any]]] = None,
        user_env: Optional[Dict[str, str]] = None,
        execution_id: Optional[str] = None,
    ):
        if not emit_message:
            raise ValueError("emit_message callback is required")

        self.config = config
        self.conversation_id = conversation_id or f"conv_{int(time.time() * 1000)}"
        self.user_id = user_id
        self.workflow_id = workflow_id
        self.node_id = node_id
        # Workflow execution this agent run belongs to — keys the durable
        # tool-call records (tool_call_events) for execute_bash.
        self.execution_id = execution_id

        # Caller context we pass through unchanged so other code paths (billing,
        # debug routing, MCP auth) can still find what they expect.
        self._sid = sid
        self._user_email = user_email
        self._sio = sio
        self._env = env or {}
        self._enable_persistence = enable_persistence
        self._organization_id = organization_id

        self._emit_message = emit_message
        self._custom_tool_executor = custom_tool_executor

        # Sandbox runtime — created up front (cheap, no I/O) for every
        # workflow agent node, so the model can always reach for a shell.
        # The actual sandbox is brought up lazily inside
        # _runtime.ensure_sandbox() on the first execute_bash call — an
        # agent that never touches the shell pays nothing. ``_runtime`` is
        # the attribute name tool_execution._execute_filesystem_tool reads
        # to find the sandbox for upload_file. None outside workflow runs
        # (the interactive coder chat passes no node_id).
        self._runtime = (
            create_sandbox_runtime(
                filesystem_configs=filesystem_configs or [],
                workflow_id=workflow_id,
                node_id=node_id,
                conversation_key=conversation_key,
                sandbox_setups=sandbox_setups or [],
                user_env=user_env or {},
            )
            if workflow_id and node_id
            else None
        )

        # Conversation history. Two paths:
        #
        # 1. Persistent (chat UI, workflow chats with conversation_key set):
        #    enable_persistence=True + conversation_id → PostgresSession.
        #    The SDK Runner auto-prepends history and auto-writes new items
        #    on every run. Survives container restarts because storage is
        #    Postgres (conversations.metadata.sdk_history JSONB).
        #
        # 2. Transient (smoke tests, one-shot internal runs without a
        #    conversation_id): no session, ``_history`` accumulates input
        #    items in-memory across calls within one Agent instance.
        #
        # The branch is decided in create() — once set, it doesn't change.
        self._session: Optional[PostgresSession] = None
        self._history: List[Dict[str, Any]] = []

        # The underlying agents.Agent (set during _build_sdk_agent in create()).
        self._sdk_agent: Optional[SDKAgent] = None

        # The CostCapturingLitellmModel that backs ``self._sdk_agent.model``;
        # held separately so BillingHooks can read provider-reported cost off
        # ``last_call_cost`` in ``on_llm_end``. Rebuilt by ``update_model``.
        self._sdk_model: Optional[CostCapturingLitellmModel] = None

        # Billing lifecycle hook. Built in create() once we have the model
        # resolved on the config. Equivalent to TrackingLLM in the OpenHands
        # wrapper: pre-call balance check + post-call usage_tracker emission.
        self._billing_hooks: Optional[BillingHooks] = None

        # Tracks the currently-running RunResultStreaming so ``pause()`` can
        # cancel it. Set inside ``__call__`` for the duration of a run, then
        # cleared. ``pause()`` reads this and calls ``.cancel("immediate")``.
        self._active_result: Optional[Any] = None

        # Current working directory advertised to the LLM and used by future
        # cwd-aware tools. Set by ``set_working_directory`` (called by the
        # chat handler when the user picks an app folder). Today this is
        # purely informational — execute_bash routes through the sandbox's
        # mount_path regardless — but we keep the value so any future
        # cwd-aware behavior (a prompt insertion, a tool argument default,
        # etc.) has it available.
        self._current_workdir: str = "/tmp/apps"

        # Whether create() has finished. Until then, ``__call__`` raises.
        self._initialized = False

    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #
    @classmethod
    async def create(
        cls,
        emit_message: Callable[..., Awaitable[None]],
        config: Optional[AgentConfiguration] = None,
        conversation_id: Optional[str] = None,
        sid: Optional[str] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        sio: Optional[Any] = None,
        env: Optional[Dict[str, str]] = None,
        enable_persistence: bool = True,
        custom_tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        organization_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        node_id: Optional[str] = None,
        filesystem_configs: Optional[List[Dict[str, Any]]] = None,
        conversation_key: Optional[str] = None,
        sandbox_setups: Optional[List[Dict[str, Any]]] = None,
        user_env: Optional[Dict[str, str]] = None,
        execution_id: Optional[str] = None,
        **kwargs,
    ) -> "Agent":
        """Async factory for ``Agent``.

        Accepts either a pre-built ``AgentConfiguration`` or loose
        keyword arguments that flow through ``AgentConfiguration.from_kwargs``.
        The kwarg form preserves backwards compatibility with the
        legacy call surface (``model=..., system_prompt=..., custom_tools=...``).
        """
        if config is None:
            config = AgentConfiguration.from_kwargs(**kwargs)

        agent = cls(
            emit_message=emit_message,
            config=config,
            conversation_id=conversation_id,
            sid=sid,
            user_id=user_id,
            user_email=user_email,
            sio=sio,
            env=env,
            enable_persistence=enable_persistence,
            custom_tool_executor=custom_tool_executor,
            organization_id=organization_id,
            workflow_id=workflow_id,
            node_id=node_id,
            filesystem_configs=filesystem_configs,
            conversation_key=conversation_key,
            sandbox_setups=sandbox_setups,
            user_env=user_env,
            execution_id=execution_id,
        )
        agent._build_sdk_agent()
        agent._build_billing_hooks()
        # Hook up the durable Session iff caller asked for persistence AND
        # gave us a conversation_id to key it on. Falls through to the
        # transient in-memory ``_history`` path otherwise.
        if enable_persistence and conversation_id:
            agent._session = PostgresSession(
                conversation_id=conversation_id,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=node_id,
            )
        agent._initialized = True
        return agent

    def _build_billing_hooks(self) -> None:
        """Construct the per-Agent BillingHooks.

        Skipped only without a user_id (test path). No try/except: a missing
        socket must NOT drop billing — triggered runs (sid="") still record.
        """
        if not self.user_id:
            logger.info(
                "[openai_agent] no user_id — skipping BillingHooks (test path)"
            )
            return
        self._billing_hooks = BillingHooks(
            model=self.config.llm.model,
            model_instance=self._sdk_model,
            user_id=self.user_id,
            sio=self._sio,
            sid=self._sid,
            organization_id=self._organization_id,
            env=self._env,
        )

    def _build_sdk_agent(self) -> None:
        """Instantiate the underlying agents.Agent.

        Creation itself spawns zero threads (verified by
        debug_openai_agents_spike.py:test_agent_creation_only). Tools are
        wired through FunctionTool wrappers whose on_invoke_tool calls our
        _custom_tool_executor.

        When ``self._runtime`` is set (every workflow agent node), we
        also expose ``execute_bash`` as a built-in tool the model can
        call directly. The OpenAI Agents SDK has no built-in shell
        tool, so we wire one ourselves — calls route through
        ``SandboxRuntime.run_bash``, which obtains the configured workspace
        runtime on first use.
        """
        instructions = self.config.settings.system_prompt or self._default_instructions()

        # The OpenAI Agents SDK's tool surface alone is often not
        # enough — without an explicit hint, models default to writing
        # prose instead of invoking ``execute_bash`` (OpenHands' built-in
        # prompt used to carry this). Suffix a short capability note when
        # a sandbox runtime is attached so the user-supplied prompt
        # doesn't have to know about this.
        if self._runtime is not None:
            mount = getattr(self._runtime, "mount_path", "/workspace")
            # Only a FilesystemNode-backed sandbox persists; a provider-mount-only
            # sandbox is ephemeral disk. Telling the model the wrong contract makes
            # it either trust vanishing files or needlessly re-fetch durable ones.
            if getattr(self._runtime, "persistent", False):
                persistence = (
                    f"Files you write under `{mount}` survive across runs — they are "
                    "available next time. Keep anything you want to persist there."
                )
            else:
                persistence = (
                    "This sandbox is ephemeral: files do NOT survive after this run "
                    "ends, so treat it as scratch space."
                )
            # Runtime-declared quirk of the mount mechanics (e.g. the hosted
            # runtime's symlinked volume mounts); empty for real-dir mounts.
            caveat = getattr(self._runtime, "mount_caveat", "")
            instructions = (
                f"{instructions}\n\n"
                f"You have access to a Linux sandbox at `{mount}`. Use the "
                "`execute_bash` tool to read, write, and manipulate files there; "
                f"run scripts; inspect state. {persistence} "
                f"{caveat + ' ' if caveat else ''}Prefer calling "
                "`execute_bash` over describing what you would do."
            )
        model_name = self.config.llm.model

        # All non-OpenAI providers route through LiteLLM so we keep the custom
        # cost-tracking fork. OpenAI native models could use the SDK's default
        # OpenAIResponsesModel, but routing through LitellmModel keeps the
        # cost path uniform for now.
        # ``CostCapturingLitellmModel`` intercepts the raw LiteLLM result inside
        # ``_fetch_response`` so the provider-reported cost is captured BEFORE
        # the SDK's response transformation strips it. Held on ``self`` so
        # ``BillingHooks`` can read ``last_call_cost`` in ``on_llm_end``.
        sdk_model = _build_sdk_model(model_name, self._env)
        self._sdk_model = sdk_model

        tools = self._build_tools_from_config()
        if self._runtime is not None:
            tools.append(self._make_execute_bash_tool())

        from nodes.agent.rehearsal import is_rehearsal_conversation

        self._sdk_agent = SDKAgent(
            name=f"noclick-{self.conversation_id}",
            instructions=instructions,
            model=sdk_model,
            tools=tools,
            model_settings=_build_model_settings(
                model_name, self.config.llm.temperature,
                rehearsing=is_rehearsal_conversation(self.conversation_id),
            ),
        )
        logger.info(
            "[openai_agent] Built SDK Agent: conversation=%s model=%s tools=%d sandbox=%s",
            self.conversation_id,
            model_name,
            len(tools),
            self._runtime is not None,
        )

    def _build_tools_from_config(self) -> List[FunctionTool]:
        """Convert config.capabilities.custom_tools into SDK FunctionTool list.

        The input shape is the OpenAI ChatCompletionToolParam dict:
            {"type": "function", "function": {"name", "description", "parameters"}}

        Each FunctionTool routes its on_invoke_tool call to our
        ``_custom_tool_executor`` (the async callback the consumer registered
        in nodes/agent/handlers/llm.py). The arguments arrive as a JSON
        string from the SDK; we parse them and pass a dict to the executor.
        Return values are JSON-serialized so the SDK can feed them back to
        the model as tool output. If the executor returns a non-JSON-able
        value, we fall back to str().
        """
        custom_tools = self.config.capabilities.custom_tools or []
        if not custom_tools:
            return []
        if self._custom_tool_executor is None:
            logger.warning(
                "[openai_agent] %d custom_tools registered but no _custom_tool_executor — "
                "tools will appear in the model's tool list but cannot be invoked",
                len(custom_tools),
            )

        sdk_tools: List[FunctionTool] = []
        for tool_def in custom_tools:
            fn = tool_def.get("function") or {}
            name = fn.get("name")
            description = fn.get("description") or ""
            parameters = fn.get("parameters") or {"type": "object", "properties": {}}
            if not name:
                logger.warning("[openai_agent] skipping tool with no name: %r", tool_def)
                continue
            sdk_tools.append(self._make_function_tool(name, description, parameters))
        return sdk_tools

    def _make_function_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> FunctionTool:
        executor = self._custom_tool_executor  # bind for closure

        async def on_invoke_tool(ctx: Any, args_json: str) -> str:
            try:
                args = json.loads(args_json) if args_json else {}
            except json.JSONDecodeError as e:
                err = f"Invalid JSON arguments for tool {name!r}: {e}"
                logger.warning("[openai_agent] %s — raw: %r", err, args_json)
                return json.dumps({"error": err})

            if executor is None:
                return json.dumps({"error": f"No executor registered for tool {name!r}"})

            try:
                result = await executor(name, args)
            except Exception as e:
                logger.error("[openai_agent] tool %r raised: %s", name, e, exc_info=True)
                return json.dumps({"error": str(e), "tool": name})

            # Feed the result back to the model as a JSON string. The SDK
            # expects str output from on_invoke_tool.
            try:
                return json.dumps(result, default=str)
            except (TypeError, ValueError):
                return str(result)

        return FunctionTool(
            name=name,
            description=description,
            params_json_schema=self._coerce_strict_schema(parameters),
            on_invoke_tool=on_invoke_tool,
            # strict_json_schema=True enforces OpenAI's strict tool schema
            # rules (no additionalProperties=True at root, every property
            # required, etc.). User-supplied tool schemas often violate this,
            # so we relax the constraint and rely on the model to honor the
            # description. Phase-4.5 follow-up: tighten schemas where we can.
            strict_json_schema=False,
        )

    def _make_execute_bash_tool(self) -> FunctionTool:
        """Build the built-in ``execute_bash`` FunctionTool.

        Only created when ``self._runtime`` exists. Schema matches what
        OpenHands' built-in execute_bash exposed (just ``command`` —
        timeout/soft_timeout were OpenHands-specific knobs the model
        rarely used). The model sees one tool, calls it with a shell
        string, the sandbox runs it and returns
        ``{stdout, stderr, exit_code}``.
        """
        runtime = self._runtime  # bind for closure
        assert runtime is not None  # narrowed by caller

        def _record_bash(command: str, result: Dict[str, Any], start: float) -> None:
            # Durable per-call record, same table as node_op/MCP tools
            # (utils.tool_call_log). execute_bash bypasses the
            # tool_execution.execute_tool choke point (it's a direct SDK
            # FunctionTool), so it records here. Infra failures are "error";
            # a command exiting non-zero executed fine — the exit code rides
            # in the preview instead of inflating the failure count.
            from utils.tool_call_log import record_tool_call

            try:
                _model = self.model
            except Exception:
                _model = None
            infra_error = result.get("error")
            preview = (
                None if infra_error else
                f"exit {result.get('exit_code')}"
                f" | stdout: {(result.get('stdout') or '')[-300:]}"
                f" | stderr: {(result.get('stderr') or '')[-150:]}"
            )
            record_tool_call(
                user_id=self.user_id,
                tool_name="execute_bash",
                tool_type="bash",
                result_status="error" if infra_error else "success",
                workflow_id=str(self.workflow_id) if self.workflow_id else None,
                execution_id=self.execution_id,
                conversation_id=self.conversation_id,
                agent_node_id=self.node_id,
                provider_node_id=(
                    runtime._fs_config.get("node_id") if runtime._fs_config else None
                ),
                arguments={"command": command},
                error=str(infra_error)[:500] if infra_error else None,
                result_preview=preview[:500] if preview else None,
                duration_ms=(time.monotonic() - start) * 1000,
                model=_model,
            )

        async def on_invoke_tool(ctx: Any, args_json: str) -> str:
            try:
                args = json.loads(args_json) if args_json else {}
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid JSON arguments: {e}"})

            command = args.get("command")
            # One unambiguous log line per invocation so it's trivial
            # to grep for "did the model actually call execute_bash?"
            # in a tmux capture. Trimmed to 200 chars so a long script
            # doesn't blow up the log line.
            logger.info(
                "[execute_bash] invoked: command=%r (model has reached the tool)",
                (command or "")[:200],
            )
            if not command or not isinstance(command, str):
                return json.dumps(
                    {"error": "execute_bash requires a non-empty 'command' string"}
                )

            start = time.monotonic()

            # A rehearsal fabricates every outward effect. execute_bash
            # bypasses the tool_execution.execute_tool choke point (it's a
            # direct SDK FunctionTool), so it consults the same Redis gate
            # here — a Test Run must never boot a real sandbox.
            from nodes.agent.rehearsal import (
                RehearsalUnavailable,
                is_rehearsing,
                mock_tool_call,
            )

            if await is_rehearsing(self.conversation_id):
                try:
                    fabricated = await mock_tool_call(
                        conversation_id=self.conversation_id,
                        tool_name="execute_bash",
                        arguments={"command": command},
                        description=(
                            "Executes a shell command in the agent's Linux "
                            "sandbox. Respond with a JSON object of exactly "
                            '{"stdout": str, "stderr": str, "exit_code": int}.'
                        ),
                    )
                except RehearsalUnavailable as e:
                    result = {"error": f"rehearsal could not simulate this call: {e}"}
                    _record_bash(command, result, start)
                    return json.dumps(result)
                if not isinstance(fabricated, dict) or "exit_code" not in fabricated:
                    # World model drifted off the pinned shape — wrap so the
                    # agent still sees the execute_bash contract.
                    fabricated = {
                        "stdout": json.dumps(fabricated, default=str),
                        "stderr": "",
                        "exit_code": 0,
                    }
                fabricated = clip_bash_result(fabricated)
                _record_bash(command, fabricated, start)
                return json.dumps(fabricated, default=str)

            try:
                result = await runtime.run_bash(command)
            except Exception as e:
                logger.error("[openai_agent] execute_bash raised: %s", e, exc_info=True)
                _record_bash(command, {"error": str(e)}, start)
                return json.dumps({"error": str(e)})

            # Uncapped output once put a cat'ed PDF (millions of tokens) into
            # the model request + persisted history, bricking the conversation
            # (2026-08-24) — every result is bounded before it leaves the tool.
            result = clip_bash_result(result)
            _record_bash(command, result, start)
            return json.dumps(result, default=str)

        # Mounted-repo note: the one sentence that lets the model compose
        # clone → edit → push → create_pull_request without prompt engineering.
        from nodes.agent.git_mounts import describe_git_mounts

        mounts_note = describe_git_mounts(runtime.sandbox_setups, runtime.mount_path)

        # Names only — the values are in the shell for the model to use, but
        # putting them here would persist secrets into conversation history.
        from nodes.agent.user_env import describe_user_env

        env_note = describe_user_env(runtime.user_env)

        return FunctionTool(
            name="execute_bash",
            description=(
                "Execute a shell command in a sandboxed Linux environment with "
                "a persistent filesystem mounted at the workspace path. Returns "
                "stdout, stderr, and exit_code. Use this for reading, writing, "
                "and manipulating files; running scripts; and inspecting state."
                + (f" {mounts_note}" if mounts_note else "")
                + (f" {env_note}" if env_note else "")
            ),
            params_json_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute (sh -c).",
                    },
                },
                "required": ["command"],
            },
            on_invoke_tool=on_invoke_tool,
            strict_json_schema=False,
        )

    async def _emit_run_item_event(self, ev: RunItemStreamEvent) -> None:
        """Translate SDK RunItemStreamEvent → ChatMessageEvent.agentic_steps.

        Tool calls + their results surface as an AgenticStep nested inside
        a ChatMessageEvent (the wire shape OpenHands used and the chat UI
        already knows how to render).

        Other RunItem kinds (message_output_created, handoff_*, mcp_*,
        reasoning_item_created) are ignored here. Reasoning is already
        streamed chunk-by-chunk via response.reasoning.delta in the raw
        path above; full message output is finalized by the post-loop
        completion emission.
        """
        from wss.sender.events import tool_call_step_text, tool_step_event

        name = ev.name
        item = ev.item
        if name == "tool_called":
            tool_name = getattr(item, "tool_name", None) or "<unknown>"
            call_id = getattr(item, "call_id", None) or tool_name
            # Arguments live on the raw OpenAI tool-call item we wrap inside
            # the SDK's ToolCallItem. Pull JSON string and parse for the
            # frontend; fall back to raw if parsing fails.
            raw = getattr(item, "to_input_item", None)
            args: Any = None
            try:
                input_item = raw() if callable(raw) else None
                if input_item and isinstance(input_item, dict):
                    arg_json = input_item.get("arguments") or input_item.get("function", {}).get("arguments")
                    if arg_json:
                        args = json.loads(arg_json) if isinstance(arg_json, str) else arg_json
            except Exception:
                args = None
            await self._emit_message(
                tool_step_event(str(call_id), tool_call_step_text(tool_name, args), "in_progress")
            )
        elif name == "tool_output":
            call_id = getattr(item, "call_id", None) or "tool"
            # ToolCallOutputItem stores the output in different fields across
            # versions; pull both common ones and emit whichever is set.
            # Completes the AgenticStep matching the tool_called id above —
            # the chat UI keys steps by id and updates the row in place.
            output = getattr(item, "output", None) or getattr(item, "result", None)
            await self._emit_message(
                tool_step_event(str(call_id), str(output) if output is not None else "", "completed")
            )
        # All other RunItem kinds intentionally not surfaced.

    @staticmethod
    def _coerce_strict_schema(parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure params_json_schema has the minimum shape the SDK expects.

        SDK requires a top-level object schema with at least ``type`` set.
        User-supplied parameter dicts sometimes omit ``type`` or pass an
        empty dict — patch those up here to avoid the model rejecting the
        tool definition.
        """
        if not isinstance(parameters, dict) or not parameters:
            return {"type": "object", "properties": {}}
        if parameters.get("type") is None:
            parameters = {**parameters, "type": "object"}
        if "properties" not in parameters:
            parameters = {**parameters, "properties": {}}
        return parameters

    @staticmethod
    def _default_instructions() -> str:
        """Minimal fallback if the caller didn't supply one. Replaced by
        the NoClickAgent prompt once Phase 2 ports the agent prompt template."""
        return "You are a helpful assistant."

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #
    async def __call__(self, message: Dict[str, Any]) -> None:
        """Process a user message via the agent — streaming.

        ``message`` shape (preserved from the OpenHands wrapper):
            {"content_items": [ContentItem(...), ...]}

        Streaming wire format emitted via ``self._emit_message``:
          - per chunk:     {"type": "agent_message_chunk", "role": "assistant",
                            "content": "<chunk text>"}
          - on completion: {"type": "agent_message",       "role": "assistant",
                            "content": "<full text>",     "finished": True}
          - on error:      {"type": "agent_message",       "role": "assistant",
                            "content": "Error: ...",      "finished": True,
                            "error": "<message>"}

        Multi-turn: ``self._history`` accumulates the SDK input_list across
        calls. Phase 2 keeps this in-memory; Phase 7 swaps in a Session.
        """
        if not self._initialized or self._sdk_agent is None:
            raise RuntimeError("Agent not initialized — call await Agent.create(...)")

        user_content = self._build_user_input(message)
        # str for text-only turns (compact history rows), a content-part list
        # when the turn carries images — either way it's one user turn.
        new_turn = (
            user_content
            if isinstance(user_content, str)
            else [{"role": "user", "content": user_content}]
        )
        # Decide the input shape based on which history backend is active:
        #   - PostgresSession path: pass just the new user turn; the SDK
        #     Runner auto-prepends prior items via session.get_items() and
        #     auto-writes new items via session.add_items() on completion.
        #   - In-memory path: prepend self._history manually and persist
        #     the new turn at the end of this call.
        if self._session is not None:
            input_list = new_turn
        elif self._history:
            input_list = self._history + [{"role": "user", "content": user_content}]
        else:
            input_list = new_turn

        accumulated_text = ""
        result = None
        # Rehearsals surface the agent's reasoning between tool calls as
        # thought rows in the live trace. Pure prefix check — no I/O. getattr:
        # turn-loop test rigs build Agent via __new__ and never mint an id.
        from nodes.agent.rehearsal import is_rehearsal_conversation
        rehearsing = is_rehearsal_conversation(getattr(self, "conversation_id", None))
        thought_buf: List[str] = []
        # Apply the env overrides LiteLLM expects for the duration of this
        # run. build_litellm_env() returns the platform-key mask + user-key
        # overlay if env was provided, or just provider aliases (e.g.
        # GEMINI_API_KEY → GOOGLE_API_KEY) if using platform keys.
        env_overrides = build_litellm_env(self._env)
        for attempt in range(_LLM_RUN_ATTEMPTS):
            accumulated_text = ""
            # Run items (tool calls/outputs) are side effects — a turn that
            # produced ANY is never retried (see _is_retryable_llm_error).
            turn_had_items = False
            result = None
            env_ctx = override_env(**env_overrides) if env_overrides else contextlib.nullcontext()
            try:
                with env_ctx:
                    result = Runner.run_streamed(
                        self._sdk_agent,
                        input_list,
                        hooks=self._billing_hooks,
                        session=self._session,
                        max_turns=AGENT_MAX_TURNS,
                    )
                    # Expose to pause() so the chat UI's stop button can cancel
                    # this run. Cleared in the finally below — pause() on a
                    # completed Agent is a no-op.
                    self._active_result = result
                    async for ev in result.stream_events():
                        # Content / reasoning deltas come through as RawResponsesStreamEvent
                        # whose inner .data is one of the openai.types.responses event types.
                        # See debug_openai_agents_spike.py for the event shape we probed.
                        if isinstance(ev, RawResponsesStreamEvent):
                            data = ev.data
                            data_type = getattr(data, "type", "")
                            delta = getattr(data, "delta", None)
                            if not delta:
                                continue
                            if data_type == "response.output_text.delta":
                                accumulated_text += delta
                                if rehearsing:
                                    thought_buf.append(delta)
                                # ChatMessageEvent.message is a streamable field —
                                # multiple events concatenate on the consumer side
                                # (see agent_node.emit_callback's
                                # ``final_response_ref[0] += event.message``).
                                await self._emit_message(ChatMessageEvent(
                                    message=delta,
                                    finished=False,
                                ))
                            elif data_type in (
                                "response.reasoning.delta",
                                "response.reasoning_summary_text.delta",
                            ):
                                # Reasoning models (o1, deepseek-r1, …) emit thinking
                                # deltas before the visible content. Surface them
                                # as a 'Thinking' status on ChatMessageEvent so the
                                # chat UI shows the thinking pulse while reasoning
                                # is happening.
                                if rehearsing:
                                    thought_buf.append(delta)
                                await self._emit_message(ChatMessageEvent(
                                    message=None,
                                    status="Thinking",
                                    finished=False,
                                ))
                        elif isinstance(ev, RunItemStreamEvent):
                            # Item completions (full message, tool_called, tool_output, …).
                            # Surface tool_called + tool_output to the frontend so
                            # the activity feed can render what the agent did.
                            turn_had_items = True
                            if rehearsing and ev.name == "tool_called" and thought_buf:
                                # Flush the reasoning/text accumulated since the
                                # last call as a thought row ABOVE the tool row
                                # it explains. Text after the LAST call is the
                                # final reply — the done frame owns that, so it
                                # never flushes here.
                                from nodes.agent.rehearsal import emit_rehearsal_thought
                                thought = "".join(thought_buf)
                                thought_buf.clear()
                                await emit_rehearsal_thought(self.conversation_id, thought)
                            await self._emit_run_item_event(ev)
                        # AgentUpdatedStreamEvent and other lifecycle events are not
                        # surfaced to the frontend.
            except InsufficientBalanceError as e:
                # BillingHooks already emitted CreditsExhaustedEvent. Surface a
                # finished message so the caller's await unblocks cleanly and
                # the frontend transitions from streaming → terminal state.
                # Pair with AgentStateEvent(state='error') so workflow callers
                # know to mark the run as failed (vs completed with the error
                # string as the response, which would silently succeed).
                # Both carry the gate's message verbatim: its shape is the
                # contract (billing.exceptions) that downstream consumers —
                # the top-up error button, the credits email routing — key on;
                # an ad-hoc slug here made SDK-path exhaustion invisible to
                # both.
                logger.warning("[openai_agent] run aborted: %s", e)
                await self._emit_message(ChatMessageEvent(
                    message=str(e),
                    finished=True,
                ))
                await self._emit_message(AgentStateEvent(
                    state="error",
                    reason=str(e),
                ))
                return
            except Exception as e:
                if (
                    attempt + 1 < _LLM_RUN_ATTEMPTS
                    and not accumulated_text
                    and not turn_had_items
                    and _is_retryable_llm_error(e)
                ):
                    delay = _retry_delay(attempt)
                    logger.warning(
                        "[openai_agent] transient LLM error on attempt %d/%d, "
                        "retrying in %.1fs: %s",
                        attempt + 1, _LLM_RUN_ATTEMPTS, delay, e,
                    )
                    await self._emit_message(ChatMessageEvent(
                        message=None,
                        status="Retrying",
                        finished=False,
                    ))
                    await asyncio.sleep(delay)
                    continue
                logger.error("[openai_agent] streaming run failed: %s", e, exc_info=True)
                # Provider billing/auth rejections (litellm surfaces them as
                # raw exception text) get the actionable rewrite — the same
                # classifier used by CLI harnesses.
                from nodes.agent.provider_errors import classify_provider_error

                match = classify_provider_error(str(e), channel="error")
                reason = match.message if match else str(e)
                await self._emit_message(ChatMessageEvent(
                    message=f"Error: {reason}",
                    finished=True,
                ))
                await self._emit_message(AgentStateEvent(
                    state="error",
                    reason=reason,
                ))
                return
            finally:
                # Always drop the active-result reference. pause() that arrives
                # after the run completes (e.g. user click race) should be a
                # no-op, not a NoneType.cancel() crash.
                self._active_result = None
            break  # attempt succeeded

        # Persist updated history for multi-turn — only when running on the
        # in-memory backend. With a PostgresSession the SDK has already
        # written the new items via session.add_items() during the run.
        if self._session is None:
            try:
                self._history = result.to_input_list()
            except Exception:
                # If the stream ended abnormally before final state is built
                # we fall back to appending the user + accumulated assistant
                # turn so the next call still has the right context.
                self._history = (
                    (self._history or [])
                    + [
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": accumulated_text},
                    ]
                )

        # Streamable chunks already populated the consumer's accumulator,
        # so the completion event carries no new message text — it just
        # flips ``finished=True``. If for some reason no chunks were
        # emitted (zero-output model response), fall back to
        # ``result.final_output`` so the consumer at least sees the full
        # text once. Setting message=None when chunks streamed avoids
        # doubling the response text on the consumer side.
        if accumulated_text:
            final_message: Optional[str] = None
        else:
            final_message = (result.final_output if result else None) or None
        await self._emit_message(ChatMessageEvent(
            message=final_message,
            finished=True,
        ))

    @staticmethod
    def _build_user_input(
        message: Dict[str, Any],
    ) -> Union[str, List[Dict[str, Any]]]:
        """Convert the OpenHands-style {"content_items": [...]} shape into
        the SDK user-content value.

        Text-only turns keep the plain-string content (unchanged wire shape,
        and history rows stay compact). Turns carrying image items return the
        SDK's multi-content form — ``[{"type": "input_text", ...},
        {"type": "input_image", ...}]`` — so vision blocks actually reach the
        model instead of being flattened away (the old behavior silently
        dropped every image_url item).
        """
        items = message.get("content_items", [])
        text_parts: List[str] = []
        image_parts: List[Dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                item = ContentItem(**item)
            if not isinstance(item, ContentItem):
                continue
            if item.type == "text" and item.text:
                text_parts.append(item.text)
            elif item.type == "image_url":
                url = item.get_image_url()
                if not url:
                    continue
                detail = (
                    item.image_url.detail
                    if isinstance(item.image_url, ImageUrl) and item.image_url.detail
                    else "auto"
                )
                image_parts.append(
                    {"type": "input_image", "image_url": url, "detail": detail}
                )
        text = "\n".join(text_parts)
        if not image_parts:
            return text
        content: List[Dict[str, Any]] = []
        if text:
            content.append({"type": "input_text", "text": text})
        content.extend(image_parts)
        return content

    # ------------------------------------------------------------------ #
    # Chat-handler surface — methods + properties the wss agent_handler
    # (chat:message socket event) calls on a live Agent instance during
    # an interactive session.
    # ------------------------------------------------------------------ #
    @property
    def model(self) -> str:
        """LLM model currently configured. Read by the chat handler to
        decide whether ``update_model`` needs to fire when the user
        toggles the model dropdown."""
        return self.config.llm.model

    @property
    def env(self) -> Dict[str, str]:
        """Effective env-overrides dict. Read by the chat handler to
        decide whether ``update_model`` needs to re-key the LLM (e.g.
        the user switched from platform keys to BYO keys)."""
        return self._env

    async def set_working_directory(self, path: str) -> None:
        """Record the agent's working directory.

        The OpenHands wrapper used this to rebind the runtime's cwd so
        bash commands ran from the right folder; that was meaningful
        because OpenHands' runtime carried per-action cwd state. Our
        SandboxRuntime always runs at ``mount_path`` (the FilesystemNode
        volume mount) and ignores per-request cwd, so this is currently
        a tracked-but-passive setting — readable via
        ``agent._current_workdir`` but not yet plumbed into
        ``execute_bash``.

        Reasons to keep it: (a) the chat handler reads
        ``agent._current_workdir`` to short-circuit redundant cwd
        updates; (b) a follow-up could prepend ``cd {path} &&`` to
        sandbox commands when the agent both has a sandbox and the
        path is inside the mount; (c) we want the call to succeed so
        the chat UI's "select app folder" feature works post-cutover.
        """
        normalized = self._normalize_workdir(path)
        if normalized == self._current_workdir:
            return
        self._current_workdir = normalized
        logger.info(
            "[openai_agent] working directory set: conversation=%s path=%s",
            self.conversation_id, normalized,
        )

    @staticmethod
    def _normalize_workdir(path: str) -> str:
        """Validate + normalize a workspace path.

        Matches the OpenHands wrapper's allowlist
        (``/workspace`` or ``/tmp/apps``). Anything outside raises so
        the caller doesn't silently lose context.
        """
        import posixpath
        if not path:
            raise ValueError("Working directory path cannot be empty")
        normalized = posixpath.normpath(path)
        if not (normalized.startswith("/workspace") or normalized.startswith("/tmp/apps")):
            raise ValueError(
                f"Working directory must be within /workspace or /tmp/apps: {normalized}"
            )
        return normalized

    async def pause(self) -> None:
        """Cancel the currently-running stream, if any.

        Uses ``RunResultStreaming.cancel("immediate")``: stops execution,
        cancels associated tasks, clears event queues. Safe to call when
        no run is active — ``_active_result`` is None outside a
        ``__call__`` invocation and we no-op in that case.

        The chat handler ``handle_pause`` calls this from the
        ``agent:pause`` socket event when the user clicks "stop".
        """
        result = self._active_result
        if result is None:
            logger.info(
                "[openai_agent] pause requested but no active run: conversation=%s",
                self.conversation_id,
            )
            return
        try:
            result.cancel(mode="immediate")
            logger.info(
                "[openai_agent] paused active run: conversation=%s",
                self.conversation_id,
            )
        except Exception as e:
            logger.warning("[openai_agent] cancel() raised (continuing): %s", e)

    def update_model(
        self,
        model: str,
        temperature: Optional[float] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Swap the underlying LLM mid-conversation.

        The chat UI fires this when the user picks a different model
        from the dropdown after the conversation has started. History
        (``self._history``) is preserved across the swap — the next
        call to ``__call__`` will run the new model against the full
        accumulated input list.

        Args:
            model: New model name (e.g. ``openrouter/openai/gpt-4o-mini``).
            temperature: New temperature; ``None`` keeps the current value.
            env: New env-overrides dict; ``None`` clears overrides
                (matches OpenHands' contract — passing None means
                "go back to platform keys").
        """
        old_model = self.config.llm.model
        self.config.llm.model = model
        if temperature is not None:
            self.config.llm.temperature = temperature
        # Match OpenHands: None means clear, not "skip update".
        self._env = env or {}

        # Rebuild the underlying SDK Agent so the new LitellmModel is
        # picked up. Cheaper than recreating Agent — the tools list
        # (including any sandbox-backed execute_bash) is reused.
        # The new model instance also becomes the cost-capture slot the
        # rebuilt BillingHooks reads from.
        if self._sdk_agent is not None:
            self._sdk_model = _build_sdk_model(model, self._env)
            self._sdk_agent.model = self._sdk_model
            # Settings are per-PROVIDER, not per-conversation: a swap from an
            # openrouter model to a groq one must shed the OpenRouter usage
            # extension, or every request 400s. This is exactly the builder's
            # model-churn path, so the stale-settings variant of the BYOK
            # bug lived here.
            from nodes.agent.rehearsal import is_rehearsal_conversation

            self._sdk_agent.model_settings = _build_model_settings(
                model, self.config.llm.temperature,
                rehearsing=is_rehearsal_conversation(self.conversation_id),
            )

        # Rebuild: model name is baked into UsageEventData + cost lookups.
        # No try/except — see _build_billing_hooks.
        if self._billing_hooks is not None:
            self._billing_hooks = BillingHooks(
                model=model,
                model_instance=self._sdk_model,
                user_id=self.user_id,
                sio=self._sio,
                sid=self._sid,
                organization_id=self._organization_id,
                env=self._env,
            )

        logger.info(
            "[openai_agent] model updated: conversation=%s %s → %s temp=%s",
            self.conversation_id, old_model, model, self.config.llm.temperature,
        )

    # ------------------------------------------------------------------ #
    # Cleanup
    # ------------------------------------------------------------------ #
    async def cleanup(self) -> None:
        """Release per-Agent resources.

        Versus the OpenHands wrapper this is a much shorter list — the
        SDK creates no EventStream, no ThreadPoolExecutors, no controller,
        no session_volume commit loop. We keep the method on the public
        surface to preserve the ``finally: await agent.cleanup()``
        pattern in nodes/agent/handlers/llm.py.

        Concretely we:

        - Close the sandbox runtime, if one was created, so its implementation
          can persist workspace changes and release its resources.

        - Drop the SDK Agent reference so its model + accumulated input
          history are GC-eligible.

        No explicit Session flush is needed: PostgresSession.add_items()
        commits to Postgres synchronously inside each ``Runner.run_streamed``
        turn, so by the time cleanup runs everything is already durable.
        """
        if not self._initialized:
            return
        self._initialized = False

        if self._runtime is not None:
            try:
                await self._runtime.close()
            except Exception as e:
                logger.warning(
                    "[openai_agent] sandbox close failed (continuing): %s",
                    e, exc_info=True,
                )

        logger.info("[openai_agent] cleanup() for conversation %s", self.conversation_id)
        self._sdk_agent = None
        self._sdk_model = None
        self._history = []
