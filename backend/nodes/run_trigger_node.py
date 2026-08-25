"""
Run trigger node implementation.

This node acts as the deterministic entry point for workflows when the user
clicks the "Run" button. When present, it takes highest priority over all
other trigger types in _find_input_node().
"""

import time
import logging
from typing import Dict, Any

from nodes.core.base import WorkflowNode

logger = logging.getLogger(__name__)


class RunTriggerNode(WorkflowNode):
    """
    Run trigger node.

    Acts as the primary entry point for manual workflow execution.
    When present, this node takes priority over all other trigger types,
    providing a deterministic start point regardless of node positioning.
    """

    edit_examples = [
        "Use this as the manual entry point for the workflow",
        "Replace other triggers so this is the only workflow start",
        "Change the workflow to start from this node when clicking Run",
        "Make this the primary trigger that fires when user clicks Run",
        "Ensure this node has priority over other trigger types",
        "Designate this as the deterministic entry point",
    ]

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[RunTriggerNode] Executing node {self.node_id}")

        output = {
            "type": "run-trigger",
            "status": "triggered",
            "timestamp": time.time(),
        }

        await self.emit(output)
        return output
