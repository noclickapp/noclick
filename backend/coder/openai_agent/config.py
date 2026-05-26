"""AgentConfiguration for the OpenAI Agents SDK-backed Agent.

Ported verbatim from the OpenHands-era `coder/openhands/config/agent_config.py`
during the Phase 9 cutover. The module had no actual OpenHands dependency —
just dataclasses and a TYPE_CHECKING reference to litellm.ChatCompletionToolParam
— so the migration is a straight copy.

Two notes for future readers:

  - Some flags (``enable_browsing``, ``enable_editor``, ``enable_jupyter``,
    ``runtime_type``) are dead in the new wrapper — they were OpenHands knobs.
    We keep them in ``from_kwargs`` so existing call sites don't have to
    sanitize their kwargs; the new Agent simply ignores them.

  - ``enable_cmd`` is replaced functionally by passing ``filesystem_configs``
    to ``Agent.create`` directly. The flag still exists for backwards
    compatibility but the wrapper no longer reads it.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from litellm import ChatCompletionToolParam


class StreamingState(Enum):
    """State machine for agent streaming responses."""

    NOT_STREAMING = "not_streaming"
    WAITING_FOR_STREAM = "waiting_for_stream"
    STREAMING = "streaming"
    COMPLETE = "complete"


@dataclass
class WorkspaceConfig:
    """Workspace configuration."""

    path: Optional[str] = None


@dataclass
class LLMConfig:
    """LLM configuration."""

    model: str = "gpt-4"
    temperature: float = 0.0
    env: Optional[Dict[str, str]] = None


@dataclass
class AgentCapabilities:
    """Agent capability flags."""

    enable_mcp: bool = False
    mcp_server_url: str = "http://localhost:8000/mcp"
    enable_browsing: bool = False
    enable_cmd: bool = False
    enable_editor: bool = False
    enable_jupyter: bool = False
    # Custom tools from workflow ToolNodes (ChatCompletionToolParam dicts)
    custom_tools: Optional[List["ChatCompletionToolParam"]] = None
    # Filesystem volume configs from connected FilesystemNodes
    filesystem_configs: Optional[List[Dict[str, Any]]] = None

    @property
    def custom_tool_names(self) -> Optional[List[str]]:
        """Extract tool names from custom_tools definitions."""
        if not self.custom_tools:
            return None
        return [tool["function"]["name"] for tool in self.custom_tools]


@dataclass
class RuntimeConfig:
    """Runtime configuration."""

    runtime_type: str = "fast_local"
    file_store: str = "memory"
    enable_browser: bool = False


@dataclass
class AgentSettings:
    """Agent-specific settings."""

    default_agent: str = "NoClickAgent"
    max_iterations: int = 50
    system_prompt: Optional[str] = None


@dataclass
class AgentTimeouts:
    """Configurable timeout values."""

    base_event_timeout: float = 0.5
    max_event_timeout: float = 2.0
    max_timeout_count: int = 20
    background_task_timeout: float = 5.0


@dataclass
class AgentConfiguration:
    """Complete agent configuration."""

    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    settings: AgentSettings = field(default_factory=AgentSettings)
    timeouts: AgentTimeouts = field(default_factory=AgentTimeouts)

    @classmethod
    def from_kwargs(cls, **kwargs) -> "AgentConfiguration":
        """Build a configuration from loose keyword arguments.

        Used by Agent.create when the caller didn't pass a fully-formed
        AgentConfiguration object — e.g. legacy callers that still pass
        ``model=..., system_prompt=..., custom_tools=...`` directly.
        """
        return cls(
            workspace=WorkspaceConfig(path=kwargs.get("workspace_path")),
            llm=LLMConfig(
                model=kwargs.get("model", "gpt-4"),
                temperature=kwargs.get("temperature", 0.0),
                env=kwargs.get("env"),
            ),
            capabilities=AgentCapabilities(
                enable_mcp=kwargs.get("enable_mcp", False),
                mcp_server_url=kwargs.get("mcp_server_url", "http://localhost:8000/mcp"),
                enable_browsing=kwargs.get("enable_browsing", False),
                enable_cmd=kwargs.get("enable_cmd", False),
                enable_editor=kwargs.get("enable_editor", False),
                enable_jupyter=kwargs.get("enable_jupyter", False),
                custom_tools=kwargs.get("custom_tools"),
                filesystem_configs=kwargs.get("filesystem_configs"),
            ),
            runtime=RuntimeConfig(
                runtime_type=kwargs.get("runtime_type", "fast_local"),
                file_store=kwargs.get("file_store", "memory"),
                enable_browser=kwargs.get("enable_browser", False),
            ),
            settings=AgentSettings(
                default_agent=kwargs.get("default_agent", "NoClickAgent"),
                max_iterations=kwargs.get("max_iterations", 500),
                system_prompt=kwargs.get("system_prompt"),
            ),
        )
