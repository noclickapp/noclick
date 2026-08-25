"""
AI Agent node implementation.

Handles AI agent operations such as processing requests with LLMs,
executing commands, reading files, etc. Uses the OpenAI Agents
SDK-backed wrapper at ``coder/openai_agent/`` for actual AI processing
with streaming support.

Supports custom tools from connected ToolNodes, enabling the agent
to call HTTP endpoints, execute code, and other operations defined
in the workflow.
"""

import asyncio
import os
import json
import logging
import re
from typing import Dict, Any, Optional, Sequence, Tuple, List, Type, Union
from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk
from nodes.core.base import WorkflowNode
from nodes.core.dynamic_options import filter_options_by_search

from utils.cost_monitoring import apply_model_substitution
from wss.sender import send_event, ChatMessageEvent, AgentStateEvent
from wss.sender.schema import ContentItem, ImageUrl

logger = logging.getLogger(__name__)


# Upstream output types that hand TOOLS to an agent (all arrive via the
# agent's bottom handle). Collection of every one of these is edge-scoped —
# see _is_wired_tool_provider.
_AGENT_TOOL_OUTPUT_TYPES = {
    "tool_definition",
    "mcp_tool_definitions",
    "alarm_tool_definitions",
    "alarm_trigger",
    "filesystem_config",
    "node_op_tool_provider",
    "node_op_tool_provider_bundle",
}

_GOOGLE_GENERATIVE_LANGUAGE_ORIGIN = "https://generativelanguage.googleapis.com"
_HTTP_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


async def _download_agent_video(client, url: str, api_key: Optional[str]):
    """Download one generated video without leaking provider credentials.

    Google returns media URLs that can redirect to a signed storage URL.  The
    API key belongs only on the exact Generative Language origin; HTTPX keeps
    custom headers across redirects, so follow each hop explicitly and decide
    afresh whether that hop may receive the key.  The guarded client still
    validates and pins every destination before connecting.
    """
    from utils.ssrf import SSRFError, assert_exact_url_origin

    current_url = str(url)
    max_redirects = 10
    for redirect_count in range(max_redirects + 1):
        headers: Dict[str, str] = {}
        if api_key:
            try:
                assert_exact_url_origin(
                    current_url,
                    _GOOGLE_GENERATIVE_LANGUAGE_ORIGIN,
                )
            except SSRFError:
                pass
            else:
                headers["x-goog-api-key"] = api_key

        response = await client.get(
            current_url,
            headers=headers,
            follow_redirects=False,
        )
        if response.status_code not in _HTTP_REDIRECT_STATUSES:
            return response

        location = response.headers.get("location")
        if not location:
            return response
        if redirect_count == max_redirects:
            raise RuntimeError("Generated-video download exceeded redirect limit")
        current_url = str(response.url.join(location))

    raise RuntimeError("Generated-video download exceeded redirect limit")


# ============================================================================
# JSON Parsing Utilities
# ============================================================================


def extract_json_from_markdown(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract and parse JSON from text that may be wrapped in markdown code blocks.

    Handles formats like:
    - ```json\n{...}\n```
    - ```\n{...}\n```
    - Raw JSON: {...}

    Args:
        text: Text potentially containing JSON

    Returns:
        Parsed JSON dict if found and valid, None otherwise
    """
    if not text or not isinstance(text, str):
        return None

    # Try to find JSON within markdown code fences
    # Pattern matches: ```json (optional), then {...} content, then ```
    patterns = [
        r"```json\s*\n(.*?)\n```",  # ```json\n{...}\n```
        r"```\s*\n(.*?)\n```",  # ```\n{...}\n```
        r"^\s*(\{.*\})\s*$",  # Raw JSON object
        r"^\s*(\[.*\])\s*$",  # Raw JSON array
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.debug(
                    f"[extract_json_from_markdown] Failed to parse JSON from pattern {pattern}"
                )
                continue

    # If no pattern matched, try parsing the entire string as JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        logger.debug(
            f"[extract_json_from_markdown] Could not extract valid JSON from text"
        )
        return None


# ============================================================================
# Config imports (from nodes/agent/config/ package)
# ============================================================================

from nodes.agent.config import (
    AGENT_ENV_CREDENTIAL_TYPE,
    AgentConfig,
    AgentCredentials,
    AgentNodeConfig,
    PROVIDER_REQUIRED_CREDENTIALS,
    WRAPPER_ID_BY_MODEL_TYPE,
    filter_provider_credential_env,
    get_provider_credentials,
    match_model_credential,
    resolve_agent_cred_model,
)
from nodes.agent.harness_registry import get_cli_turn_runner

# ============================================================================
# Reference extraction helper
# ============================================================================


def _extract_referenced_node_ids(
    config: dict, workflow_nodes: Optional[List[dict]] = None
) -> set:
    """Extract node ids referenced anywhere in a config dict.

    Recognizes both grammars used in NoClick inline expressions:
    - Legacy ``{{nodeId.path}}`` — first segment is the node id.
    - JS-accessor ``{{ $('nodeId').field }}`` — each ``$('id')`` literal.

    When ``workflow_nodes`` is provided, label-keyed accessors like
    ``$('My Label')`` are resolved to the corresponding node id (the JS
    evaluator accepts labels alongside ids; without resolution the alarm
    capture pass would miss them).
    """
    from utils.expression_evaluator import (
        _scan_blocks,
        extract_expression_node_ids,
        is_js_expression,
    )

    label_to_id: dict[str, str] = {}
    for n in workflow_nodes or []:
        nid = n.get("id")
        if not nid:
            continue
        # Node lists arrive in two shapes: saved-blob (label under config.label)
        # and FE/runtime (label under data.label). Cover both.
        label = (n.get("data") or {}).get("label") or (n.get("config") or {}).get("label")
        if label:
            label_to_id.setdefault(label, nid)

    ids: set = set()

    def scan(val):
        if isinstance(val, str):
            for _start, _end, inner in _scan_blocks(val):
                if is_js_expression(inner):
                    for raw in extract_expression_node_ids(inner):
                        ids.add(label_to_id.get(raw, raw))
                else:
                    first = inner.strip().split(".")[0].split("[")[0]
                    if first and not first.startswith("$"):
                        ids.add(first)
        elif isinstance(val, dict):
            for v in val.values():
                scan(v)
        elif isinstance(val, list):
            for v in val:
                scan(v)

    scan(config)
    return ids


class AgentNode(WorkflowNode):
    """
    AI Agent node backed by the OpenAI Agents SDK wrapper.

    Integrates with ``coder/openai_agent/`` for:
    - LLM-powered task execution
    - Sandbox-backed command execution (when a FilesystemNode is attached)
    - Streaming responses with real-time callbacks
    - Custom tools from connected ToolNodes
    """

    edit_examples = [
        "Change model harness to OpenCode",
        "Set temperature to 0.7 for more randomness",
        "Enable conversation memory to resume chat",
        "Switch to Claude Code for code generation",
        "Disable streaming for faster responses",
        "Add system prompt guidance",
    ]

    # Workflow context for executing tool downstream nodes
    _execute_downstream_callback: Optional[Any] = None
    # Resolved conversation_key for the current run, captured at execute()
    # time so downstream collaborators (e.g. registered CLI runner) can derive
    # the same chat_routing_id without re-parsing the config.
    _conversation_key: Optional[str] = None
    # True once a terminal signal (finished chat:message or error agent:state)
    # has reached the chat surface this run. Guards execute()'s failure wrapper
    # from double-emitting an error the harness already reported.
    _terminal_state_emitted: bool = False

    def chat_routing_id(self) -> str:
        """The conversation_id this node's chat events flow under.

        Single source of truth: when a conversation_key is captured for the
        current run (set in execute() — alarm-trigger key wins over config),
        the id is ``ck:{workflow}:{node}:{key}``. Otherwise it falls back to
        an externally-provided conversation_id (workflow chat) and finally
        to the node id. The CLI sandbox runner reads this so its status /
        final-response emits land in the same conversation_id the frontend
        AgentChatBlock subscribes to.
        """
        ck = self._conversation_key
        if ck and self.workflow_id and self.node_id:
            return f"ck:{self.workflow_id}:{self.node_id}:{ck}"
        return self.conversation_id or self.node_id

    @classmethod
    def should_propagate_output(
        cls, output: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        """A no-op'd builder wake turn (nothing left to relay) produced no
        agent turn — downstream nodes must not run on its placeholder output."""
        return not (isinstance(output, dict) and output.get("skipped"))

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic options for agent node fields.

        Every upstream here returns the full catalog in one call (no cursor,
        no native search). Search mode is therefore a pure substring filter
        applied with the shared :func:`filter_options_by_search` helper.
        """
        if field_name == "model":
            import asyncio
            from utils.model_catalog import list_all_models

            # Mirrors AGENT_NODE_PRIORITY_MODELS in AIAgentNode.tsx — keep the
            # CLI agents at the top, matching the on-canvas ModelDropdown.
            priority_ids = ("codex", "claude-code", "opencode", "openclaw", "hermes")
            priority_rank = {mid: i for i, mid in enumerate(priority_ids)}

            def to_option(m) -> dict:
                # Prefix the label with the routing provider (e.g. "openrouter")
                # unless that would just repeat the display (CLI agents where
                # id == provider).
                display = m.name or m.id
                normalized = m.provider.replace("_", "-").lower() if m.provider else ""
                label = f"[{m.provider}] {display}" if m.provider and normalized != display.lower() else display
                if m.free:
                    # Also what makes these match a "free" substring search.
                    label = f"{label} · Free"
                return {
                    "value": m.id,
                    "label": label,
                    "metadata": {"provider": m.provider, "source": m.source},
                }

            # list_all_models() may make a blocking requests.get to OpenRouter
            # on cache miss (10-min TTL). Offload so we don't stall the event loop.
            all_models = await asyncio.to_thread(list_all_models)
            text_models = [m for m in all_models if "text" in m.output_modalities]
            text_models.sort(key=lambda m: priority_rank.get(m.id, len(priority_ids)))
            options = [to_option(m) for m in text_models]
            return {
                "options": filter_options_by_search(options, search),
                "next_page_token": None,
            }
        if field_name == "opencode_model":
            from nodes.agent.config.harness_model_lists import fetch_opencode_models

            options = await fetch_opencode_models()
            return {
                "options": filter_options_by_search(options, search),
                "next_page_token": None,
            }
        if field_name == "codex_model":
            from nodes.agent.config._cli_models_loader import codex_options

            # no_change_needed: helper is a small static list; search arg ignored.
            return {"options": codex_options(), "next_page_token": None}
        if field_name == "claude_code_model":
            from nodes.agent.config._cli_models_loader import claude_code_options

            # no_change_needed: helper is a small static list; search arg ignored.
            return {"options": claude_code_options(), "next_page_token": None}
        if field_name == "hermes_agent_model":
            from nodes.agent.config.harness_model_lists import fetch_hermes_agent_models

            options = await fetch_hermes_agent_models()
            return {
                "options": filter_options_by_search(options, search),
                "next_page_token": None,
            }
        if field_name == "openclaw_model":
            from nodes.agent.config.harness_model_lists import fetch_openclaw_models

            options = await fetch_openclaw_models()
            return {
                "options": filter_options_by_search(options, search),
                "next_page_token": None,
            }
        return {"options": [], "next_page_token": None}

    # ---------------------------------------------------------------- #
    # Chat history persistence
    #
    # Under OpenHands, ``PostgresStore`` auto-wrote every user message +
    # agent reply to ``conversations.events`` as the EventStream flowed
    # through. Phase 9 deleted PostgresStore in favor of ``PostgresSession``
    # — which writes the SDK's input items to ``metadata.sdk_history``
    # but NOT to ``events`` / ``title`` / ``preview``. Those columns are
    # what the chat-history sidebar + ``conversation:resume`` flow read,
    # so without writes here the UI shows an empty sidebar and blank
    # restores even though the LLM context (sdk_history) persists fine.
    #
    # Event shape must match what ``mapPersistedMessage`` on the FE
    # consumes — ``{role: 'user'|'assistant', message: str, ...}`` —
    # NOT the OpenHands-legacy ``{action, source, args.content}`` shape.
    # ---------------------------------------------------------------- #
    _UPSERT_INTERFACE_EVENT_SQL = """
        INSERT INTO conversations (
            conversation_id, user_id, workflow_id, node_id,
            events, title, preview, agent_model,
            created_at, last_activity
        )
        VALUES ($1, $2, $3, $4, $5, $6, $6, $7, NOW(), NOW())
        ON CONFLICT (conversation_id) DO UPDATE
        SET events = COALESCE(conversations.events, '[]'::jsonb) || EXCLUDED.events,
            last_activity = NOW(),
            deleted_at = NULL,
            workflow_id = COALESCE(conversations.workflow_id, EXCLUDED.workflow_id),
            node_id = COALESCE(conversations.node_id, EXCLUDED.node_id),
            title = COALESCE(NULLIF(conversations.title, ''), EXCLUDED.title),
            preview = COALESCE(NULLIF(conversations.preview, ''), EXCLUDED.preview),
            agent_model = COALESCE(conversations.agent_model, EXCLUDED.agent_model)
    """

    async def _persist_interface_chat_event(
        self,
        *,
        conversation_id: str,
        role: str,
        message: str,
        model: Optional[str],
        label: Optional[str] = None,
        cancelled: bool = False,
        image_urls: Optional[List[str]] = None,
        video_urls: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Append one event to ``conversations.events`` so the chat-history
        sidebar + restore on the interface AgentChatBlock see this turn.

        ``image_urls`` / ``video_urls`` carry media so a reload restores them
        as image_url/video_url content items — generated media on assistant
        turns (image / video / kling fast-path handlers, image-generating LLM
        tools) and user-attached images on user turns. ``attachments`` carries
        the user's non-image files (``{name, url, mime_type}``) restored as
        chips on the user bubble. The restore mapper
        (useAgentChat.persistedEventsToChatMessages) reads these top-level
        fields.

        Skipped when ``self.user_id`` or ``conversation_id`` is missing
        (workflow runs without a chat surface — e.g. cron-triggered
        background runs — don't need chat-history rows).
        """
        if not (self.user_id and conversation_id):
            return
        if not (message or image_urls or video_urls or attachments):
            return
        event: Dict[str, Any] = {"role": role, "message": message}
        if role == "assistant":
            # Attach the turn's compacted tool timeline so the chat's step rows
            # survive reloads. The AgentHandler chat path gained this on
            # 2026-07-19 (#1773) but interface sends ride the workflow-execute
            # path, which kept writing stepless assistant events — every
            # remount lost the timeline. Same shared boundary gather, so the
            # window advances once per response regardless of persist path.
            try:
                from utils.tool_call_log import (
                    compact_tool_calls_for_transcript,
                    gather_turn_tool_calls,
                )

                calls = await gather_turn_tool_calls(
                    node_id=self.node_id, conversation_id=conversation_id,
                )
                compact = compact_tool_calls_for_transcript(calls) or None
                if compact:
                    event["tool_calls"] = compact
            except Exception:
                logger.warning(
                    "[AgentNode] tool-timeline gather failed", exc_info=True
                )
        if cancelled:
            event["cancelled"] = True
        if image_urls:
            event["image_urls"] = image_urls
        if video_urls:
            event["video_urls"] = video_urls
        if attachments:
            event["attachments"] = attachments
        try:
            from utils.database_pool import get_native_pool
            await get_native_pool().execute(
                self._UPSERT_INTERFACE_EVENT_SQL,
                conversation_id,
                self.user_id,
                self.workflow_id,
                self.node_id,
                [event],
                label,
                model,
            )
        except Exception as e:
            # Never block the live agent run on a persist failure; log
            # loudly so a regression that empties the chat history is
            # detectable.
            logger.warning(
                f"[AgentNode] Failed to persist {role} event for "
                f"conversation {conversation_id}: {e}"
            )

    @staticmethod
    def _media_urls_from_output(output: Any) -> Tuple[List[str], List[str]]:
        """Pull (image_urls, video_urls) out of a handler output dict. Both
        the media fast-path and the LLM path produce ``images``/``videos`` as
        lists of ``{"url": ...}`` dicts; this is the single extractor both use
        so chat display and history persistence read the same shape."""
        if not isinstance(output, dict):
            return [], []
        image_urls = [
            img["url"]
            for img in (output.get("images") or [])
            if isinstance(img, dict) and img.get("url")
        ]
        video_urls = [
            vid["url"]
            for vid in (output.get("videos") or [])
            if isinstance(vid, dict) and vid.get("url")
        ]
        return image_urls, video_urls

    async def _emit_media_chat_result(
        self,
        output: Dict[str, Any],
        *,
        conversation_id: Optional[str],
        model: Optional[str],
    ) -> None:
        """Surface a media fast-path handler's generated media in the chat
        interface. image / video / kling handlers return their output directly
        and bypass the LLM path's emit_callback, so without this their result
        never reaches the AgentChatBlock transcript (rendered from chat:message
        events) nor the chat-history restore. Emits one finished
        ChatMessageEvent carrying the images/videos as image_url/video_url
        content items and persists the assistant turn with the URLs so a reload
        restores them. No-op when the output carries no media."""
        image_urls, video_urls = self._media_urls_from_output(output)
        if not image_urls and not video_urls:
            return
        text = (output.get("response") or "").strip()
        content = [
            ContentItem(type="image_url", image_url=ImageUrl(url=url))
            for url in image_urls
        ]
        content += [
            ContentItem(type="video_url", video_url=url) for url in video_urls
        ]
        if self.sio and self.sid:
            await send_event(self.sio, self.sid, ChatMessageEvent(
                conversation_id=conversation_id or self.node_id,
                message=text or None,
                content=content,
                finished=True,
                model=model,
            ))
        await self._persist_interface_chat_event(
            conversation_id=conversation_id or "",
            role="assistant",
            message=text,
            model=model,
            image_urls=image_urls or None,
            video_urls=video_urls or None,
        )

    async def _persist_llm_assistant_turn(
        self,
        output: Any,
        *,
        conversation_id: Optional[str],
        model: Optional[str],
        raw_text: str,
        agent_errored: bool,
    ) -> None:
        """Persist the LLM path's assistant turn after execute_llm_model
        returns — the only point at which generated images have been uploaded
        to R2 (output['images'] holds durable URLs), so text + media land in
        one history row. Skipped when the agent reached an error state: the
        emit_callback AgentStateEvent branch already persisted a cancelled
        bubble for that turn. Persists the raw streamed text (not
        output['response'], which may have been replaced by parsed JSON)."""
        if agent_errored or not conversation_id or not isinstance(output, dict):
            return
        image_urls, video_urls = self._media_urls_from_output(output)
        await self._persist_interface_chat_event(
            conversation_id=conversation_id,
            role="assistant",
            message=(raw_text or "").strip(),
            model=model,
            image_urls=image_urls or None,
            video_urls=video_urls or None,
        )

    def set_workflow_context(
        self,
        execute_downstream_callback,
        workflow_nodes=None,
        workflow_edges=None,
    ) -> None:
        """
        Set the workflow context for executing tool downstream nodes.

        This context allows the agent to execute downstream nodes when
        a tool is called by the LLM.

        Args:
            execute_downstream_callback: Async callback that takes (tool_node_id, arguments)
                and executes all downstream nodes of that tool, returning combined results.
                This handles full subgraph execution with proper topological ordering
                and concurrent execution.
            workflow_nodes: Full list of workflow node dicts (for alarm upstream reference scanning)
            workflow_edges: Full list of workflow edge dicts (for alarm upstream reference scanning)
        """
        self._execute_downstream_callback = execute_downstream_callback
        self._workflow_nodes = workflow_nodes
        self._workflow_edges = workflow_edges

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Agent node"""
        return AgentNodeConfig

    def _is_wired_tool_provider(self, provider_node_id: str) -> bool:
        """Whether an upstream tool surface is wired into THIS agent's bottom
        handle. Tool collection (and the filesystem-volume scan) is scoped on
        this so co-resident agents never inherit each other's tools,
        credentials, or volumes. When edges are unavailable (no workflow
        context, e.g. the chat path), the legacy collect-everything semantic
        is preserved — scoping info is absent."""
        edges = getattr(self, "_workflow_edges", None)
        if edges is None:
            return True
        return any(
            e.get("source") == provider_node_id
            and e.get("target") == self.node_id
            and e.get("targetHandle") == "bottom"
            for e in edges
        )

    def _collect_tool_definitions(
        self, inputs: Dict[str, Any]
    ) -> Tuple[List[ChatCompletionToolParam], Dict[str, Dict], List[Dict[str, Any]]]:
        """
        Collect tool definitions from connected ToolNodes, MCPServerNodes, and AlarmNodes.

        Scans the inputs for:
        - type='tool_definition': Single tool from ToolNode
        - type='mcp_tool_definitions': Multiple tools from MCPServerNode
        - type='alarm_tool_definitions': Multiple tools from AlarmNode
        - type='alarm_trigger': Alarm fired — contains embedded tool_definitions
          (the wake-up message itself is delivered via _resolve_trigger_event)
        - type='node_op_tool_provider': Integration node exposing allowlisted operations as tools

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Tuple of (list of tool params for LLM, dict mapping tool names to their configs,
                       list of unresolved sandbox mount requests)
        """
        tool_params = []
        tool_configs = {}  # Maps tool_name -> full config for execution
        sandbox_mounts = []  # Provider-requested sandbox environment (e.g. repo clones)

        # Tool names are {provider_slug}__{operation}; when MULTIPLE providers
        # of the same node type feed THIS agent (e.g. two Slack workspaces),
        # type-derived slugs would collide and tool_configs.update() would
        # silently rebind every call to the last provider's credential.
        # Duplicates get slugs from the user-given node LABEL ("Work Linear" →
        # work_linear__create_issue) — the label is the semantic signal the
        # MODEL uses to pick the right provider; the node id is only the
        # uniqueness fallback. Counted up front so renaming is deterministic.
        provider_type_counts: Dict[str, int] = {}
        for provider_id, output in inputs.items():
            if not (isinstance(output, dict) and self._is_wired_tool_provider(provider_id)):
                continue
            if output.get("type") == "node_op_tool_provider":
                nt = output.get("node_type", "")
                provider_type_counts[nt] = provider_type_counts.get(nt, 0) + 1
            elif output.get("type") == "node_op_tool_provider_bundle":
                # Hosting-mode MCP node: its bundled providers count toward
                # the same collision space as directly-wired ones.
                for entry in output.get("providers", []):
                    nt = entry.get("node_type", "")
                    provider_type_counts[nt] = provider_type_counts.get(nt, 0) + 1
        used_provider_slugs: set = set()

        def _provider_slug_for(provider_node_id: str, label: Optional[str]) -> str:
            slugify = lambda s: re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()  # noqa: E731
            slug = slugify(label) if label else ""
            if not slug or slug in used_provider_slugs:
                slug = slugify(provider_node_id)
            used_provider_slugs.add(slug)
            return slug

        def process_tool_definition(node_id: str, tool_def: Dict[str, Any]) -> None:
            """Process a single tool definition and add to collections."""
            tool_name = tool_def.get("tool_name")
            if not tool_name:
                logger.warning(
                    f"[AgentNode] Tool from {node_id} has no tool_name, skipping"
                )
                return

            # Build tool parameter schema
            parameters = tool_def.get("parameters", [])
            properties = {}
            required = []

            for param in parameters:
                param_schema: Dict[str, Any] = {
                    "type": param.get("type", "string"),
                    "description": param.get(
                        "description", f"Parameter: {param['name']}"
                    ),
                }
                if param.get("default") is not None:
                    param_schema["default"] = param["default"]

                properties[param["name"]] = param_schema

                if param.get("required", True):
                    required.append(param["name"])

            tool_param = ChatCompletionToolParam(
                type="function",
                function=ChatCompletionToolParamFunctionChunk(
                    name=tool_name,
                    description=tool_def.get("tool_description", ""),
                    parameters={
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                ),
            )

            tool_params.append(tool_param)

            # Build tool config based on tool type
            tool_type = tool_def.get("tool_type", "workflow")
            tool_config = {
                "node_id": node_id,
                "tool_type": tool_type,
                # Store schema for delegated tool injection (CLI agents)
                "_description": tool_def.get("tool_description", ""),
                "_parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }

            # For MCP tools, store the server config and original name
            if tool_type == "mcp":
                tool_config["mcp_server_config"] = tool_def.get("mcp_server_config")
                tool_config["original_tool_name"] = tool_def.get(
                    "original_tool_name", tool_name
                )

            tool_configs[tool_name] = tool_config
            logger.info(
                f"[AgentNode] Collected {tool_type} tool '{tool_name}' from node {node_id}"
            )

        for node_id, output in inputs.items():
            if not isinstance(output, dict):
                continue

            output_type = output.get("type")

            # Every tool surface is scoped to DIRECT bottom-edge wiring: all
            # tool/MCP/alarm/filesystem/provider outputs in the run land in
            # node_outputs, but their tools (and credentials/auth configs)
            # belong only to agents they're wired into — without this, a
            # workflow with two agents hands each one the other's tools.
            if output_type in _AGENT_TOOL_OUTPUT_TYPES and not self._is_wired_tool_provider(node_id):
                logger.info(
                    f"[AgentNode] Skipping {output_type} from {node_id}: not wired to this agent"
                )
                continue

            # Single tool definition (from ToolNode)
            if output_type == "tool_definition":
                process_tool_definition(node_id, output)

            # Multiple tool definitions (from MCPServerNode or AlarmNode)
            elif output_type in ("mcp_tool_definitions", "alarm_tool_definitions"):
                for tool_def in output.get("tools", []):
                    process_tool_definition(node_id, tool_def)

            # Alarm trigger (from AlarmNode when webhook fires)
            elif output_type == "alarm_trigger":
                # Extract embedded tool definitions so agent can schedule/manage
                # alarms. The wake-up message + conversation_key ride the
                # generalized trigger-event path (_resolve_trigger_event),
                # which is keyed on the FIRED trigger — a stale alarm output
                # preloaded from a previous run can't inject a ghost wake-up.
                for tool_def in output.get("tool_definitions", []):
                    process_tool_definition(node_id, tool_def)

            # Filesystem config with embedded tools (from FilesystemNode)
            elif output_type == "filesystem_config":
                for tool_def in output.get("tools", []):
                    process_tool_definition(node_id, tool_def)

            # Integration node in tool-provider mode: expose its allowlisted
            # operations as node_op tools. Definitions are derived from the
            # node's config schema at collection time (build_node_op_tools
            # emits ready JSON-schema parameters, so this bypasses
            # process_tool_definition's param-list rebuild).
            elif output_type == "node_op_tool_provider":
                self._collect_node_op_provider(
                    node_id, output,
                    provider_type_counts, _provider_slug_for,
                    tool_params, tool_configs, sandbox_mounts,
                )

            # Hosting-mode MCP node: a bundle of provider outputs aggregated
            # from the nodes wired into ITS bottom handle. Each entry is a
            # full node_op_tool_provider output + the inner provider's
            # node_id, processed exactly like a directly-wired provider —
            # same slugs, collision handling, and sandbox mounts.
            elif output_type == "node_op_tool_provider_bundle":
                for entry in output.get("providers", []):
                    inner_id = entry.get("node_id")
                    if not inner_id:
                        logger.warning(
                            f"[AgentNode] Bundle entry from {node_id} missing node_id, skipping"
                        )
                        continue
                    self._collect_node_op_provider(
                        inner_id, entry,
                        provider_type_counts, _provider_slug_for,
                        tool_params, tool_configs, sandbox_mounts,
                    )

        # A provider mount (e.g. a GitHub repo clone) needs a sandbox even
        # without a FilesystemNode, but FilesystemNode is the only thing that
        # normally emits the upload_file tool definition.
        # Synthesize the same entry here so an agent with just a repo mount
        # can still publish artifacts (build output, generated reports, etc.)
        # as resource URLs. CLI harnesses inject their own workspace-keyed
        # upload_file and skip filesystem-type tool_configs entries, so this
        # addition is used by the SDK path.
        from nodes.filesystem_node import (
            UPLOAD_FILE_TOOL_NAME,
            get_upload_tool_definition,
        )

        if sandbox_mounts and UPLOAD_FILE_TOOL_NAME not in tool_configs:
            process_tool_definition(self.node_id, get_upload_tool_definition())
            logger.info(
                f"[AgentNode] Synthesized {UPLOAD_FILE_TOOL_NAME} for sandbox-only mount "
                f"(no FilesystemNode wired)"
            )

        # Opaque email reply: when THIS run was started by an inbound-email
        # trigger wired directly into this agent, inject the locked
        # reply-to-sender tool. Keyed on the fired trigger (not bottom-handle
        # wiring) — email deliberately has no user-wirable send provider; see
        # nodes/agent/email_reply.py for the containment model.
        found = self._find_fired_trigger(inputs)
        if found and found[0].get("type") == "trigger-email":
            from nodes.agent.email_reply import (
                EMAIL_REPLY_TOOL_NAME,
                build_email_reply_tool,
            )

            pair = build_email_reply_tool(found[0]["id"], found[1])
            if pair:
                tool_params.append(pair[0])
                tool_configs[EMAIL_REPLY_TOOL_NAME] = pair[1]
                logger.info(
                    f"[AgentNode] Injected {EMAIL_REPLY_TOOL_NAME} for fired "
                    f"email trigger {found[0]['id']}"
                )

        return tool_params, tool_configs, sandbox_mounts

    def _collect_node_op_provider(
        self,
        node_id: str,
        output: Dict[str, Any],
        provider_type_counts: Dict[str, int],
        slug_for,
        tool_params: List,
        tool_configs: Dict[str, Dict],
        sandbox_mounts: List[Dict[str, Any]],
    ) -> None:
        """Expose one integration provider's allowlisted operations as node_op
        tools (shared by directly-wired providers and hosted-MCP bundles)."""
        from nodes.agent.node_op_tools import build_node_op_tools

        colliding = provider_type_counts.get(output["node_type"], 0) > 1
        label = output.get("label")
        # Sandbox environment requests (e.g. GitHub repo clones) —
        # collected even when the op allowlist is empty: mounting
        # repos without exposing API operations is a valid setup
        # (though agents then can't open PRs — flag it).
        if output.get("sandbox_repos") and not output.get("allowed_operations"):
            logger.warning(
                f"[AgentNode] Provider {node_id} mounts repos but allowlists no "
                f"operations — the agent can push but cannot open PRs via tools"
            )
        for entry in output.get("sandbox_repos") or []:
            sandbox_mounts.append({
                "node_id": node_id,
                "node_type": output["node_type"],
                "repo": entry["repo"],
                "branch": entry.get("branch") or None,
                "credential_id": output.get("credential_id"),
            })
        try:
            op_params, op_configs = build_node_op_tools(
                output["node_type"],
                output.get("allowed_operations", []),
                node_id=node_id,
                credential_id=output.get("credential_id"),
                slug=slug_for(node_id, label) if colliding else None,
                # The label/credential tags in tool descriptions are
                # what let the model CHOOSE between same-type
                # providers; only added when there's a choice to make.
                provider_label=(label or node_id) if colliding else None,
                credential_label=output.get("credential_label") if colliding else None,
            )
        except ValueError as e:
            logger.warning(f"[AgentNode] Skipping node_op provider {node_id}: {e}")
            return
        tool_params.extend(op_params)
        tool_configs.update(op_configs)
        logger.info(
            f"[AgentNode] Collected {len(op_params)} node_op tool(s) from {node_id} "
            f"({output['node_type']})"
        )

    def _find_fired_trigger(
        self, inputs: Dict[str, Any]
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """(node, output) of the FIRED trigger wired directly into this agent
        (any handle), else None.

        The fired trigger carries ``_triggerPayload`` (injected only by the
        webhook/trigger routes) or ``_pollFired`` (stamped by the executor
        right after a poll trigger executed THIS run and emitted fresh items —
        covers manual runs, whose fresh polls used to reach the agent with no
        event). Both markers are run-scoped, so stale trigger outputs
        preloaded from previous runs can't masquerade as a fresh event.
        """
        nodes = getattr(self, "_workflow_nodes", None)
        edges = getattr(self, "_workflow_edges", None)
        if not nodes or not edges:
            return None
        direct_sources = {
            e.get("source") for e in edges if e.get("target") == self.node_id
        }
        fired = next(
            (
                n
                for n in nodes
                if isinstance(n.get("config"), dict)
                and ("_triggerPayload" in n["config"] or n["config"].get("_pollFired"))
                and n.get("id") in direct_sources
            ),
            None,
        )
        if fired is None:
            return None
        output = inputs.get(fired["id"])
        if not isinstance(output, dict):
            return None
        return fired, output

    async def _relay_builder_updates(self, conversation_id: str) -> Optional[str]:
        """Compose a platform note from this conversation's undelivered builder
        outcome events — card verdicts (``builder_decision``), parked-ask
        bridge links (``builder_ask``), and run results (``builder_result``) —
        and mark them relayed, so each reaches the model exactly once.
        Best-effort: None on any failure."""
        try:
            from repositories.conversation import ConversationRepo
            from utils.database_pool import get_native_pool

            repo = ConversationRepo(get_native_pool())
            events = await repo.fetch_unrelayed_builder_events(conversation_id)
            if not events:
                return None
            lines = []
            relay_keys = []
            for ev in events:
                kind, p = ev["kind"], ev["payload"]
                if kind == "builder_decision":
                    verdict = (
                        "APPROVED — the user sent it to the workflow builder"
                        if p.get("decision") == "approved"
                        else "DISMISSED by the user"
                    )
                    lines.append(f"- Your proposal {p.get('proposal_id')}: {verdict}")
                    relay_keys.append((kind, p.get("proposal_id")))
                elif kind == "builder_ask":
                    input_lines = []
                    has_credential = False
                    has_answerable = False
                    for inp in p.get("inputs") or []:
                        kind_str = inp.get("type") or "text"
                        if kind_str == "credential":
                            has_credential = True
                        else:
                            has_answerable = True
                        opts = inp.get("options") or []
                        opts_str = ""
                        if opts:
                            names = [o.get("label") or o.get("value") if isinstance(o, dict) else str(o) for o in opts]
                            opts_str = f"; options: {' | '.join(str(n) for n in names)}"
                        req_str = "required" if inp.get("required", True) else "optional"
                        input_lines.append(
                            f"    - [{inp.get('id')}] {inp.get('label')} ({kind_str}, {req_str}{opts_str})"
                        )
                    if not input_lines:
                        input_lines = ["    - " + q for q in (p.get("questions") or ["additional input"])]
                        has_answerable = True
                    guidance = []
                    if has_answerable:
                        guidance.append(
                            "Answer the non-credential questions YOURSELF with the "
                            "builder_respond tool (answers keyed by [id]) if you can "
                            "sensibly decide them — the run resumes immediately."
                        )
                    if has_credential:
                        guidance.append(
                            "Credential inputs can ONLY be connected by a human: "
                            f"share this no-login link through your channel: {p.get('bridge_url')}"
                        )
                    else:
                        guidance.append(
                            f"If a question needs the user, share this no-login link instead: {p.get('bridge_url')}"
                        )
                    lines.append(
                        "- The builder run PAUSED on questions:\n"
                        + "\n".join(input_lines)
                        + "\n  " + " ".join(guidance)
                        + "\n  You'll be woken with the next update either way."
                    )
                    relay_keys.append((kind, p.get("relay_id")))
                elif kind == "builder_result":
                    lines.append(f"- The builder run FINISHED: {p.get('summary')}")
                    relay_keys.append((kind, p.get("relay_id")))
            await repo.mark_builder_events_relayed(conversation_id, relay_keys)
            return (
                "--- Platform note ---\n"
                "Workflow-builder updates since your last turn:\n"
                + "\n".join(lines)
            )
        except Exception:
            logger.warning("[AgentNode] builder-update relay failed", exc_info=True)
            return None

    def _resolve_trigger_event(self, inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The event that started this run, when its trigger is wired directly
        into this agent (any handle — dataflow left or alarm/tools bottom).

        The fired trigger's OUTPUT is translated by the trigger class's
        ``resolve_agent_event`` hook into ``{text, conversation_key}``.
        Returns ``None`` when the run wasn't trigger-started, the trigger
        isn't wired to this agent, or the hook declines.
        """
        found = self._find_fired_trigger(inputs)
        if found is None:
            return None
        fired, output = found
        from nodes.core.registry import NODE_REGISTRY

        node_cls = NODE_REGISTRY.get(fired.get("type", ""))
        if node_cls is None:
            return None
        event = node_cls.resolve_agent_event(output)
        if not event:
            return None
        return {
            "node_id": fired["id"],
            "source": fired["config"].get("label") or fired.get("type", "trigger"),
            "text": event.get("text") or "",
            "conversation_key": event.get("conversation_key"),
        }

    async def _resolve_sandbox_mounts(
        self, mounts: List[Dict[str, Any]], user_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Resolve provider sandbox-mount requests into boot-ready setups.

        Credential resolution + freshen happen here (backend-side, at agent
        start) so tokens never ride through the model. A configured mount
        that cannot resolve fails the run loudly — an agent silently missing
        its repo is harder to debug than an error.
        """
        if not mounts:
            return []
        from nodes.core.registry import NODE_REGISTRY
        from nodes.core.run_op import resolve_operation_credential

        # pool=None: credential resolution/freshen resolve the native pool at
        # first actual DB use (units test these with the resolvers mocked).
        pool = None
        setups: List[Dict[str, Any]] = []
        resolved_credentials: Dict[str, Dict[str, Any]] = {}  # one resolve per credential
        for m in mounts:
            node_class = NODE_REGISTRY.get(m["node_type"])
            if node_class is None:
                raise ValueError(f"Unknown provider type for sandbox mount: {m['node_type']}")
            if not m.get("credential_id"):
                raise ValueError(
                    f"Sandbox mount {m['repo']!r} requires a credential on the "
                    f"provider node ({m['node_id']})"
                )
            credential_data = resolved_credentials.get(m["credential_id"])
            if credential_data is None:
                credential_data = await resolve_operation_credential(
                    m["credential_id"], user_id or self.user_id, pool,
                    organization_id=self.organization_id, workflow_id=self.workflow_id,
                )
                credential_data = await node_class.freshen_credential(
                    credential_data, pool=pool, user_id=user_id or self.user_id,
                    credential_id=m["credential_id"],
                )
                resolved_credentials[m["credential_id"]] = credential_data
            setup = node_class.get_sandbox_setup(
                repo=m["repo"], branch=m.get("branch"), credential_data=credential_data,
            )
            if setup is None:
                raise ValueError(
                    f"{m['node_type']} does not support sandbox mounts "
                    f"(agent_sandbox_repo set on {m['node_id']})"
                )
            setup["provider_node_id"] = m["node_id"]
            setups.append(setup)
            logger.info(
                f"[AgentNode] Sandbox mount resolved: {setup['repo']} from {m['node_id']}"
            )
        return setups

    def _env_credential_id(self) -> Optional[str]:
        """The node's ``agent_env`` credential id, read from the credentialIds map.

        The map is the canonical reference location — it is what the pre-delete
        impact scan and authorize_credentials_for_workflow read, so a config-field
        pointer would be invisible to both (deleting the credential would warn
        about nothing, and collaborator runs would fail the fail-closed
        owner-fallback gate).
        """
        from utils.credentials import extract_credential_ids

        cred_ids = self.node_data.get("credentialIds")
        if not isinstance(cred_ids, dict):
            cred_ids = extract_credential_ids(self.node_data)
        value = cred_ids.get(AGENT_ENV_CREDENTIAL_TYPE)
        return value if isinstance(value, str) and value.strip() and "{{" not in value else None

    async def _resolve_user_env(
        self, env_credential_id: Optional[str], user_id: Optional[str]
    ) -> Dict[str, str]:
        """Resolve the agent's ``agent_env`` credential into sandbox env vars.

        Resolved by the node rather than the execution handler because that handler
        decrypts exactly ONE credential per node (pick_credential_id) — which the
        model-provider credential claims. Same shape as _resolve_sandbox_mounts:
        backend-side resolution, fail loud. A configured bundle that can't resolve
        or contains a reserved name fails the run — an agent silently missing the
        key it was told to use is worse than an error.
        """
        if not env_credential_id:
            return {}
        from nodes.agent.user_env import sanitize_user_env
        from nodes.core.run_op import resolve_operation_credential

        # pool=None: resolution resolves the native pool at first actual DB use.
        credential_data = await resolve_operation_credential(
            env_credential_id, user_id or self.user_id, None,
            organization_id=self.organization_id, workflow_id=self.workflow_id,
        )
        # Stored under `env`; tolerate a flat bundle the same way AgentCredentials
        # does, since both shapes reach the credentials table from the FE. The key's
        # PRESENCE decides — an empty/None `env` means an empty bundle, not a cue to
        # reinterpret the wrapper's own keys as variables.
        if "env" in credential_data:
            raw = credential_data["env"] or {}
        else:
            raw = {k: v for k, v in credential_data.items() if k != "credential_type"}
        env = sanitize_user_env(raw)
        logger.info(
            f"[AgentNode] Sandbox env resolved: {len(env)} var(s) from "
            f"credential {env_credential_id}"
        )
        return env

    async def _resolve_model_env_overrides(
        self,
        config: Any,
        credentials: Any,
        user_id: Optional[str],
        *,
        provider_name: str,
        required_vars: Sequence[str],
        cred_model: str,
    ) -> Optional[Dict[str, str]]:
        """Model-KEYED credential resolution — the run-time guarantee that the
        env riding a model call belongs to that model's provider.

        credentialIds is written by many surfaces (FE panel, builder, MCP,
        restores) and any of them can leave a stale entry after a model switch;
        the execution handler's pick_credential_id then decrypts whatever sits
        first in the map. Downstream, build_litellm_env treats ANY user env as
        "this run is BYOK" and masks every platform key, so a mismatched bundle
        doesn't just go unused — it poisons the call (OpenRouter 401 / OpenAI
        "Incorrect API key: N/A"; 2026-08-09 BYOK incident). Enforcing the match at
        this seam — the one every execute path crosses — makes the class
        impossible regardless of which surface wrote the graph:

        - the attachment matching the model's provider is used (the handler's
          decrypt when it picked right, else resolved by id here);
        - a non-matching attachment is IGNORED: the run behaves exactly as if
          no model credential were attached (platform keys where the platform
          serves the provider; the existing missing-credential failure where
          it doesn't, e.g. the always-BYOK CLI harnesses);
        - media model types retain their legacy attachment lookup, but only the
          exact keys consumed by the selected fast-path handler survive.
        """
        from utils.credentials import extract_credential_ids

        handler_bundle = (
            credentials.credentials
            if (credentials and getattr(credentials, "credentials", None))
            else None
        )
        model_type = str(getattr(config, "model_type", "llm") or "llm")
        if model_type in ("image", "video", "kling"):
            return filter_provider_credential_env(
                handler_bundle,
                provider_name=provider_name,
                required_vars=required_vars,
                cred_model=cred_model,
                model_type=model_type,
            )

        cred_ids = extract_credential_ids(self.node_data) or {}
        match = match_model_credential(config, cred_ids)
        if match is None:
            if handler_bundle is not None:
                attached = sorted(k for k in cred_ids if k != "credential_type")
                logger.warning(
                    f"[AgentNode] Attached credential(s) {attached} do not match "
                    f"provider '{provider_name}' for model '{cred_model}' — "
                    f"ignoring them and running as unattached"
                )
            return None

        _match_type, match_id = match
        if handler_bundle is not None and self.node_data.get("credential_id") == match_id:
            bundle: Dict[str, str] = handler_bundle
        else:
            # The handler decrypted a different map entry (or none) — resolve
            # the matching credential ourselves, same policy as _resolve_user_env.
            from nodes.core.run_op import resolve_operation_credential

            data = await resolve_operation_credential(
                match_id,
                user_id or self.user_id,
                None,
                organization_id=self.organization_id,
                workflow_id=self.workflow_id,
            )
            # Same shape tolerance as the AgentCredentials parse: bundles nest
            # under `credentials`, legacy rows are flat.
            if "credentials" in data:
                bundle = data["credentials"] or {}
            else:
                bundle = {k: v for k, v in data.items() if k != "credential_type"}

        # Subscription-OAuth tokens (Claude Pro/Max, ChatGPT) expire within
        # hours and the sandbox can never persist a rotation, so freshen them
        # against the credential row of record before every dispatch.
        from nodes.agent.harness_oauth import ensure_fresh_harness_tokens

        bundle = await ensure_fresh_harness_tokens(
            bundle,
            user_id=user_id,
            credential_id=match_id,
            caller_path="execute",
        )

        bundle = filter_provider_credential_env(
            bundle,
            provider_name=provider_name,
            required_vars=required_vars,
            cred_model=cred_model,
            model_type=model_type,
        )

        missing = [v for v in required_vars if not bundle or v not in bundle]
        if missing:
            logger.warning(
                f"[AgentNode] Missing credentials for {provider_name}: {missing}"
            )
        return bundle

    async def _execute_tool(
        self, tool_name: str, arguments: Dict[str, Any], tool_configs: Dict[str, Dict]
    ) -> Dict[str, Any]:
        """Delegate tool execution to the extracted tool_execution module."""
        from nodes.agent.tool_execution import execute_tool

        return await execute_tool(self, tool_name, arguments, tool_configs)

    async def _upload_images_to_r2(
        self, image_data_urls: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Upload base64 image data URIs to R2 as workflow resources.
        External URLs are passed through without uploading.

        Returns list of dicts with 'url', 'resource_id', 'mime_type', 'size_bytes'.
        """
        import base64 as b64
        from utils.database_pool import get_native_pool
        from utils.resource_store import create_resource_from_bytes

        results = []

        # Query org_id once (same for all images in this workflow)
        wf_row = await get_native_pool().fetchrow(
            "SELECT organization_id FROM workflows WHERE id = $1", self.workflow_id
        )
        org_id = wf_row["organization_id"] if wf_row else None

        for i, img_url in enumerate(image_data_urls):
            if not img_url.startswith("data:image/"):
                results.append({"url": img_url})
                continue

            try:
                header, b64_data = img_url.split(",", 1)
                mime_type = header.split(":")[1].split(";")[0]
                ext = mime_type.split("/")[1] if "/" in mime_type else "png"
                image_bytes = b64.b64decode(b64_data)

                ref = await create_resource_from_bytes(
                    user_id=self.user_id,
                    workflow_id=self.workflow_id,
                    node_id=self.node_id,
                    organization_id=org_id,
                    body=image_bytes,
                    content_type=mime_type,
                    filename=f"generated-image-{i}.{ext}",
                    resource_type="image",
                )
                results.append(
                    {
                        "url": ref["download_url"],
                        "resource_id": ref["resource_id"],
                        "mime_type": ref["mime_type"],
                        "size_bytes": ref["size_bytes"],
                    }
                )
                logger.info(
                    f"[AgentNode] Uploaded generated image to R2: {ref['storage_ref']} ({ref['size_bytes']} bytes)"
                )

            except Exception as e:
                logger.error(
                    f"[AgentNode] Failed to upload image {i} to R2: {e}", exc_info=True
                )

        return results

    async def _upload_videos_to_r2(
        self,
        video_items: List[Dict[str, Any]],
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Download videos from authenticated external URLs and upload to R2 as workflow resources.

        video_items is a list of dicts with 'url' and 'mime_type' keys.
        Google AI Studio URLs require x-goog-api-key header to download.
        Returns list of dicts with 'url', 'resource_id', 'mime_type', 'size_bytes'.
        """
        from utils.database_pool import get_native_pool
        from utils.resource_store import create_resource_from_bytes
        from utils.ssrf import guarded_async_client

        if not self.user_id or not self.workflow_id:
            logger.warning(
                f"[AgentNode] Skipping R2 upload: user_id={self.user_id}, workflow_id={self.workflow_id}"
            )
            return video_items

        results = []

        # Query org_id once (same for all videos in this workflow)
        wf_row = await get_native_pool().fetchrow(
            "SELECT organization_id FROM workflows WHERE id = $1", self.workflow_id
        )
        org_id = wf_row["organization_id"] if wf_row else None

        for i, item in enumerate(video_items):
            url = item.get("url", "")
            mime_type = item.get("mime_type", "video/mp4")
            ext = mime_type.split("/")[1] if "/" in mime_type else "mp4"

            try:
                async with guarded_async_client(timeout=300.0) as client:
                    dl_resp = await _download_agent_video(client, url, api_key)
                    dl_resp.raise_for_status()
                    video_bytes = dl_resp.content

                ref = await create_resource_from_bytes(
                    user_id=self.user_id,
                    workflow_id=self.workflow_id,
                    node_id=self.node_id,
                    organization_id=org_id,
                    body=video_bytes,
                    content_type=mime_type,
                    filename=f"generated-video-{i}.{ext}",
                    resource_type="video",
                )
                results.append(
                    {
                        "url": ref["download_url"],
                        "resource_id": ref["resource_id"],
                        "mime_type": ref["mime_type"],
                        "size_bytes": ref["size_bytes"],
                    }
                )
                logger.info(
                    f"[AgentNode] Uploaded generated video to R2: {ref['storage_ref']} ({ref['size_bytes']} bytes)"
                )

            except Exception as e:
                logger.error(
                    f"[AgentNode] Failed to upload video {i} to R2: {e}", exc_info=True
                )
                results.append(item)  # Fall back to original URL on error

        return results

    # ============================================================================
    # Handler methods have been extracted to nodes/agent/handlers/
    # - image.py, video.py, codex.py, claude_code.py, opencode.py, kling.py, llm.py
    # The execute() method below dispatches to them.
    # ============================================================================

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run the agent, guaranteeing the chat surface always gets a terminal
        signal.

        The interface chat send dispatches this node via ``workflow:execute``
        and shows a streaming indicator until it receives a terminal
        ``chat:message`` (finished) or ``agent:state`` (error) for the
        conversation. Early failures — a missing sandbox-mount credential, the
        runner-specific credential and tool-delivery setup — raise before any
        harness emits, so without this guard the workflow handler emits only a
        workflow-scoped node error and the chat dot pulses forever. On any
        exception we emit a terminal ``agent:state`` error scoped via
        ``chat_routing_id`` (unless a terminal signal already reached the
        frontend) and re-raise, leaving the handler's error bookkeeping intact.
        ``CancelledError`` (a BaseException) passes through untouched — a
        cancelled run is not a chat error.
        """
        self._terminal_state_emitted = False
        try:
            return await self._execute_impl(inputs)
        except Exception as exc:
            if not self._terminal_state_emitted:
                await self._emit_terminal_chat_error(str(exc))
            raise

    async def _emit_terminal_chat_error(self, reason: str) -> None:
        """Emit a terminal ``agent:state`` error for this run's conversation so
        the interface chat stops streaming and shows the failure, and persist it
        as a cancelled assistant bubble so a reload still shows it. Best-effort:
        a failure here must never mask the original exception."""
        conversation_id = self.chat_routing_id()
        try:
            if self.sio and self.sid:
                await send_event(
                    self.sio,
                    self.sid,
                    AgentStateEvent(
                        conversation_id=conversation_id,
                        state="error",
                        reason=reason,
                    ),
                )
            await self._persist_interface_chat_event(
                conversation_id=conversation_id,
                role="assistant",
                message=reason,
                model=getattr(self, "_effective_model", None),
                cancelled=True,
            )
        except Exception as emit_exc:
            logger.warning(
                f"[AgentNode] Failed to emit terminal chat error for "
                f"{self.node_id}: {emit_exc}"
            )
        finally:
            self._terminal_state_emitted = True

    async def _execute_impl(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute AI agent processing via the OpenAI Agents SDK wrapper.

        Args:
            inputs: Output data from upstream nodes. Expected keys:
                - 'text': Text prompt to process
                - 'content': Optional list of ContentItem dicts for multimodal input

        Returns:
            Dict containing agent processing results
        """
        logger.info(f"[AgentNode] Executing node {self.node_id}")

        # Store inputs for alarm scheduling (to capture upstream outputs)
        self._execution_inputs = inputs

        # Collect tool definitions from connected ToolNodes/AlarmNodes
        custom_tools, tool_configs, sandbox_mounts = self._collect_tool_definitions(
            inputs
        )

        if custom_tools:
            tool_names = [t["function"]["name"] for t in custom_tools]
            logger.info(
                f"[AgentNode] Found {len(custom_tools)} custom tools: {tool_names}"
            )

        # Get config - required for this node
        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[AgentNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, AgentNodeConfig):
            raise ValueError(
                f"[AgentNode] Invalid config type: {type(node_config)}, expected AgentNodeConfig"
            )

        # Extract the actual agent config and credentials
        config = node_config.config
        credentials = node_config.credentials

        # Get user_id and user_email - use self.user_id (passed from workflow execution),
        # fall back to session lookup for legacy/direct socket calls
        user_id = self.user_id
        user_email = None
        if self.sio and self.sid:
            try:
                session = await self.sio.get_session(self.sid)
                if session:
                    if not user_id:
                        user_id = session.get("user_id")
                    # Get user_email for debug features (LLM call logging)
                    user_data = session.get("user_data", {})
                    user_email = user_data.get("email") if user_data else None
            except Exception as e:
                logger.warning(f"[AgentNode] Could not get user info from session: {e}")

        original_model = config.model
        model = apply_model_substitution(
            config.model,
            workflow_id=self.workflow_id,
            node_id=self.node_id,
            user_id=user_id,
            user_email=user_email,
        )
        if model != original_model:
            config.model = model
        logger.info(
            f"[AgentNode] Using model: {config.model}, temperature: {config.temperature}"
        )

        # Trigger-event delivery: when the run was started by a trigger wired
        # directly into this agent, the fired event joins this turn's user
        # message (config.message stays the user's STANDING instructions).
        # Composed here, pre-dispatch, so all six harnesses (SDK llm + 5 CLI
        # sandboxes) see the same effective message.
        trigger_event = self._resolve_trigger_event(inputs)
        event_ck = (trigger_event or {}).get("conversation_key")
        if trigger_event and trigger_event.get("text"):
            event_block = (
                f"--- Event from {trigger_event['source']} ---\n"
                f"{trigger_event['text']}"
            )
            base_message = (config.message or "").strip()
            config.message = (
                f"{base_message}\n\n{event_block}" if base_message else event_block
            )
            logger.info(
                f"[AgentNode] Delivering trigger event from {trigger_event['node_id']} "
                f"({trigger_event['source']}), conversation_key={event_ck!r}"
            )

        # Resolve conversation_key → deterministic conversation_id
        # When conversation_key is set (for example from an upstream trigger's
        # chat/channel id), derive a stable
        # conversation_id scoped to this workflow+node so the same key always resumes
        # the same conversation history.
        effective_conversation_id = self.conversation_id
        # The fired trigger's conversation_key takes priority over config — it is
        # the medium's native thread/chat identity (Telegram chat id, Slack
        # thread, the alarm's key captured at scheduling time). EXCEPT in a
        # rehearsal, where the config carries the staged run's isolation key and
        # the event's key is the fixture's — see effective_conversation_key.
        from nodes.agent.rehearsal import effective_conversation_key

        effective_ck = effective_conversation_key(
            self.conversation_id, event_ck, config.conversation_key
        )
        self._conversation_key = effective_ck
        # Read by registered CLI runner / PostgresStore to tag conversation rows
        # with the originating harness.
        self._effective_model = config.model
        if effective_ck:
            # Written back so dispatch handlers reading config directly (llm's
            # enable_persistence + Agent.create, CLI runners) see the same key.
            config.conversation_key = effective_ck
            effective_conversation_id = (
                f"ck:{self.workflow_id}:{self.node_id}:{effective_ck}"
            )
            logger.info(
                f"[AgentNode] conversation_key={effective_ck!r} → {effective_conversation_id}"
            )

        # Emit initial status
        await self.emit({"type": "agent", "status": "starting"})

        # Persist the USER side of this turn to ``conversations.events``
        # before the agent runs — see _persist_interface_chat_event for
        # the full rationale. Writing on receive (vs on completion)
        # means the user's text still shows up in the history sidebar
        # even if the agent crashes mid-stream. ``label`` here locks
        # title + preview to the first user message via the upsert's
        # COALESCE-on-NULL clause.
        # User-attached files from the chat composer (one-shot run override,
        # like `message`). Split for persistence — images restore as bubble
        # thumbnails, other files as chips — and delivered AFTER the persist
        # capture below (so never in the persisted user bubble): agentic paths
        # (SDK llm + 5 CLI sandboxes) get a URL block in config.message; media
        # models (image/video/kling) get the images through their structured
        # input-image seams instead, since their message IS the generation
        # prompt.
        from nodes.agent.attachments import (
            MEDIA_MODEL_TYPES,
            apply_media_attachment_images,
            format_attachments_block,
            normalize_message_attachments,
            split_attachment_media,
        )

        message_attachments = normalize_message_attachments(
            getattr(config, "message_attachments", None)
        )
        attach_image_urls, attach_files = split_attachment_media(message_attachments)

        from utils.builder_bridge import WAKE_TURN_MESSAGE

        # Builder wake turns carry a sentinel, not a user message (and never
        # attachments — the wake override sets only message/ck/mockedOutput):
        # nothing to persist as a user bubble; the relay note below becomes the
        # turn, and relay notes deliberately never persist.
        is_wake_turn = (config.message or "").strip() == WAKE_TURN_MESSAGE
        user_message_text = "" if is_wake_turn else (config.message or "").strip()
        persist_user_turn: Optional[asyncio.Task] = None
        if (user_message_text or message_attachments) and effective_conversation_id:
            # Concurrent with the credential freshen below (independent I/O);
            # joined before any model dispatch so history lands first. The
            # persist swallows its own failures, so task-ifying it changes no
            # failure semantics — and it still completes even if a later
            # pre-dispatch step raises (the message should survive a crash).
            persist_user_turn = asyncio.create_task(
                self._persist_interface_chat_event(
                    conversation_id=effective_conversation_id,
                    role="user",
                    message=user_message_text,
                    model=config.model,
                    label=(
                        user_message_text
                        or ", ".join(a["name"] for a in message_attachments)
                    )[:100],
                    image_urls=attach_image_urls or None,
                    attachments=attach_files or None,
                )
            )

        # Deliver attachments post-capture, pre-dispatch.
        if message_attachments:
            if getattr(config, "model_type", "llm") in MEDIA_MODEL_TYPES:
                applied = apply_media_attachment_images(config, message_attachments)
                logger.info(
                    f"[AgentNode] Applied {applied} attached image(s) as "
                    f"{config.model_type} model input"
                )
            else:
                # Text block composed closest to the user's own words, ahead
                # of the platform notes below.
                attachments_block = format_attachments_block(message_attachments)
                base = (config.message or "").strip()
                config.message = (
                    f"{base}\n\n{attachments_block}" if base else attachments_block
                )
                logger.info(
                    f"[AgentNode] Delivering {len(message_attachments)} chat "
                    f"attachment(s) ({len(attach_image_urls)} image)"
                )

        # Relay pending prompt_builder verdicts (approve/dismiss on the card)
        # into this turn. AFTER the user-turn persist capture, so the note
        # reaches the model but never the persisted user bubble — the same
        # post-capture composition the sandbox-environment note uses. Without
        # this the agent had no channel to learn the outcome and answered from
        # its stale 'awaiting approval' tool result (2026-07-19).
        if effective_conversation_id:
            decision_note = await self._relay_builder_updates(effective_conversation_id)
            if decision_note:
                base = "" if is_wake_turn else (config.message or "").strip()
                config.message = f"{base}\n\n{decision_note}" if base else decision_note
            elif is_wake_turn:
                # Wake turn raced a concurrent turn that already relayed the
                # events (the bridge's pre-check is TOCTOU) — nothing to say,
                # so don't dispatch a ghost turn to the model.
                logger.info(
                    f"[AgentNode] Builder wake turn for {self.node_id}: nothing "
                    f"left to relay — skipping dispatch"
                )
                return {
                    "status": "success",
                    "message": "Builder wake turn: updates already relayed by a concurrent turn",
                    "skipped": True,
                }

        # Owner-presence steering for email_user — same pre-dispatch message
        # seam as the builder relay, so BOTH runtimes see it. Only composed
        # when the email tool is on (otherwise it's noise), and skipped in the
        # interface chat where the owner is by definition present.
        from nodes.agent.platform_tools import agent_email_available

        if (
            getattr(config, "enable_email_updates", "true") != "false"
            and self.user_id
            and agent_email_available()
        ):
            from nodes.agent.platform_tools import prompt_builder_mode
            from utils.user_presence import describe_owner_presence

            if prompt_builder_mode(self._conversation_key) != "interactive":
                presence_note = (
                    "--- Platform note ---\n"
                    f"The workflow owner is {await describe_owner_presence(self.user_id)}. "
                    "If you need them and they are AWAY, use the email_user tool; "
                    "if they are ACTIVE, they'll see your chat/channel output."
                )
                base = (config.message or "").strip()
                config.message = f"{base}\n\n{presence_note}" if base else presence_note

        # Track final response for return value (mutable refs so handlers can access)
        final_response_ref = [""]
        collected_images = []  # Track image URLs from ChatMessageEvent.content
        # Last AgentStateEvent (state, reason). When state == 'error' the LLM
        # handler reports status='failed' instead of silently returning the
        # error string under status='completed'.
        final_agent_state_ref: list = [None]

        # Create emit callback that forwards agent events to workflow output
        # AND streams to chat interface when socket is available
        # Use conversation_id for chat routing if set, otherwise fall back to node_id
        # conversation_id is set during workflow chat for persistent memory across messages
        chat_routing_id = effective_conversation_id or self.node_id

        async def emit_callback(event):
            if isinstance(event, ChatMessageEvent):
                # Stream to chat interface when socket available (for real-time UI)
                if self.sio and self.sid:
                    event.conversation_id = chat_routing_id
                    await send_event(self.sio, self.sid, event)
                # A finished frame is the clean-completion terminal signal the
                # frontend uses to stop streaming — record it so a post-run
                # failure doesn't overwrite a successful reply with an error.
                if getattr(event, "finished", False):
                    self._terminal_state_emitted = True

                # Forward streaming text to the node's progress slot so the
                # workflow output panel shows live activity. Progress is a
                # separate slot from node.data.output — the canonical
                # ``{type:'agent', status:'completed', ...}`` lands in
                # output via the workflow_execution_handler's final emit
                # and the frontend clears progress at that point. No race
                # with the canonical because the two writers don't share
                # storage.
                if event.message:
                    await self.emit_progress(event.message)

                # Accumulate final response
                if event.message:
                    final_response_ref[0] += event.message

                # Capture image content items for final output (from image-generating models)
                if event.content:
                    for item in event.content:
                        if hasattr(item, "type") and item.type == "image_url":
                            url = (
                                item.get_image_url()
                                if hasattr(item, "get_image_url")
                                else None
                            )
                            if url:
                                collected_images.append(url)

                # NB: the assistant turn is NOT persisted here. The generated
                # images are uploaded to R2 only AFTER the agent returns
                # (llm.py builds output['images'] post-run), so persisting on
                # the finished frame would store the text without its durable
                # image URLs. The LLM path persists the assistant turn after
                # execute_llm_model returns (see below), combining final text +
                # R2 image URLs into one history row.
            elif isinstance(event, AgentStateEvent):
                final_agent_state_ref[0] = (event.state, event.reason)
                # Stream to chat interface when socket available
                if self.sio and self.sid:
                    event.conversation_id = chat_routing_id
                    await send_event(self.sio, self.sid, event)
                if event.state == "error":
                    self._terminal_state_emitted = True

                # No node.emit() here: agent state is a transient lifecycle
                # signal (running / awaiting_user_input / error). The
                # terminal failure case is reflected in the canonical
                # WorkflowNodeOutputEvent's status='failed' + error fields,
                # so an extra ``{type:'agent_state'}`` emit would just step
                # on node.data.output without adding information.

                # Persist terminal error as an assistant bubble with
                # ``cancelled: true`` — mapPersistedMessage renders it
                # with the "Response interrupted" notice. The agent
                # already emitted a finished=True ChatMessageEvent
                # carrying the error text just before this, but the
                # cancelled flag is what triggers the FE styling.
                if event.state == "error" and effective_conversation_id:
                    reason = event.reason or "Agent terminated with an error."
                    await self._persist_interface_chat_event(
                        conversation_id=effective_conversation_id,
                        role="assistant",
                        message=reason,
                        model=config.model,
                        cancelled=True,
                    )

        # Create agent configuration
        # Determine which credentials are needed based on the model. Sub-model
        # resolution (hermes/openclaw/opencode credentials follow their
        # sub-model's provider) lives in resolve_agent_cred_model — the same
        # rule the builder's credential pipeline and the FE's
        # AgentCredentialsForm (inferProviderFromPrefix) apply.
        _cred_model = resolve_agent_cred_model(config)
        required_vars, provider_name = get_provider_credentials(_cred_model)
        env_overrides = await self._resolve_model_env_overrides(
            config,
            credentials,
            user_id,
            provider_name=provider_name,
            required_vars=required_vars,
            cred_model=_cred_model,
        )

        if persist_user_turn is not None:
            await persist_user_turn

        # Fast-path model handlers (bypass the LLM Agent wrapper)
        model_type = getattr(config, "model_type", "llm")

        # Fast-path media handlers (image / video / kling) bypass the LLM
        # Agent wrapper AND its emit_callback. Run them through this wrapper so
        # the chat interface sees the result: generated images are surfaced as
        # a finished chat:message + persisted (via _emit_media_chat_result), and
        # a failure emits a terminal AgentStateEvent so the AgentChatBlock stops
        # streaming and shows the error instead of hanging on the pulsing dot.
        if model_type in ("image", "video", "kling"):
            try:
                if model_type == "image":
                    from nodes.agent.handlers.image import execute_image_model

                    media_output = await execute_image_model(
                        self, config, env_overrides, user_id
                    )
                elif model_type == "video":
                    from nodes.agent.handlers.video import execute_video_model

                    media_output = await execute_video_model(
                        self, config, env_overrides, user_id
                    )
                else:
                    from nodes.agent.handlers.kling import execute_kling_model

                    media_output = await execute_kling_model(
                        self, config, env_overrides, user_id
                    )
            except Exception as media_exc:
                await emit_callback(
                    AgentStateEvent(state="error", reason=str(media_exc))
                )
                raise
            await self._emit_media_chat_result(
                media_output,
                conversation_id=effective_conversation_id,
                model=config.model,
            )
            return media_output

        # Platform tools — NoClick-provided, present on every agent (not
        # user-wired): submit_feedback always; prompt_builder while
        # config.enable_prompt_builder is "true" (the default). Appended after
        # the media fast-paths (no tools there) so BOTH runtimes see them: the
        # SDK agent via custom_tools, and the CLI harnesses via tool_configs on
        # their turn-scoped MCP endpoint.
        from nodes.agent.platform_tools import (
            build_platform_tools,
            inputs_are_iteration_fanout,
        )

        _in_iteration_fanout = inputs_are_iteration_fanout(inputs)
        self._in_iteration_fanout = _in_iteration_fanout

        for _p_param, _p_cfg in build_platform_tools(
            getattr(config, "enable_prompt_builder", "true") != "false",
            getattr(config, "enable_email_updates", "true") != "false",
            _in_iteration_fanout,
        ):
            custom_tools.append(_p_param)
            tool_configs[_p_param["function"]["name"]] = _p_cfg

        # CLI agents receive non-MCP tools through their registered runner.
        # Edge-scoped like all tool surfaces: another agent's filesystem
        # volume must not mount into this agent's workspace.
        filesystem_configs = [
            output
            for fs_node_id, output in inputs.items()
            if isinstance(output, dict)
            and output.get("type") == "filesystem_config"
            and self._is_wired_tool_provider(fs_node_id)
        ]

        # Provider-requested workspace setup (e.g. an authenticated GitHub
        # clone). Resolve it here with the token in hand; the selected runner
        # reads _sandbox_setups when it starts.
        self._sandbox_setups = await self._resolve_sandbox_mounts(sandbox_mounts, user_id)

        # User-supplied environment variables (agent_env credential) follow the
        # same stash-on-node pattern; the selected runner reads _user_env.
        self._user_env = await self._resolve_user_env(self._env_credential_id(), user_id)

        # CLI-harness path: dispatch through the registered turn runner
        # (nodes/agent/harness_registry owns runtime preparation and tool delivery).
        # Falls through to the SDK
        # agent when the model type has no runner claim.
        cli_runner = get_cli_turn_runner(model_type)
        if cli_runner is None and model_type in WRAPPER_ID_BY_MODEL_TYPE:
            raise RuntimeError(
                f"CLI harness model type '{model_type}' has no registered turn "
                f"runner in this build"
            )
        if cli_runner is not None:
            return await cli_runner(
                self,
                config,
                env_overrides,
                user_id,
                tool_configs,
                filesystem_configs,
                model_type=model_type,
            )

        # Default path: LLM agent via coder/openai_agent
        from nodes.agent.handlers.llm import execute_llm_model

        llm_output = await execute_llm_model(
            self,
            config,
            env_overrides,
            user_id,
            user_email,
            custom_tools=custom_tools,
            tool_configs=tool_configs,
            filesystem_configs=filesystem_configs,
            effective_conversation_id=effective_conversation_id,
            emit_callback=emit_callback,
            final_response_ref=final_response_ref,
            collected_images_ref=collected_images,
            final_agent_state_ref=final_agent_state_ref,
        )

        # Persist the assistant turn now that the handler has returned (and
        # uploaded any generated images to R2). Gated on the agent's actual
        # error STATE — not output['status'] — because the latter also flips
        # to 'failed' via a legacy heuristic when a model legitimately opens
        # its reply with "Error:"; that turn must still be saved.
        final_state = final_agent_state_ref[0] if final_agent_state_ref else None
        await self._persist_llm_assistant_turn(
            llm_output,
            conversation_id=effective_conversation_id,
            model=config.model,
            raw_text=final_response_ref[0],
            agent_errored=bool(final_state) and final_state[0] == "error",
        )
        return llm_output
