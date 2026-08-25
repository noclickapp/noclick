"""Public event contract for streaming community workflow generation."""

from dataclasses import dataclass
from typing import Any, Dict, Literal


BuilderStreamEventType = Literal[
    "node_start",
    "node_complete",
    "edge_add",
    "edge_complete",
    "input_request",
    "node_processing_start",
    "node_operation_selected",
    "node_config_filling",
    "node_updated",
    "node_added",
    "node_removed",
    "edge_added",
    "edge_removed",
    "template_match_used",
    "settings_updated",
    "run_test",
    "text_chunk",
    "generation_complete",
    "error",
    "open_workflow",
    "layout_applied",
    "status",
    "token_progress",
]


@dataclass
class BuilderStreamEvent:
    """One event emitted by a workflow builder or registered node drafter."""

    type: BuilderStreamEventType
    data: Dict[str, Any]
