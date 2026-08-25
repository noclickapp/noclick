"""
State Manager Node - Provides persistent state for Code nodes.

When connected to a Code node's bottom handle, the state is automatically:
1. Loaded from DB and injected as an input parameter named 'state'
2. Available for direct mutation in user code (state.counter += 1)
3. Persisted back to DB after code execution completes

The node stores state scoped to (workflow_id, node_id) so each State Manager
instance has its own isolated state that persists across workflow executions.
"""

import logging
import time
from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


class StateManagerInnerConfig(BaseModel):
    """Configuration for the State Manager node."""

    state: Dict[str, Any] = Field(
        default_factory=dict,
        title="State",
        description="Default state values. These serve as initial defaults and are overwritten by any persisted state from previous executions.",
        json_schema_extra={
            "ui:widget": "state_editor",
            "placeholder": '{"counter": 0, "items": []}'
        }
    )


class StateManagerNodeConfig(NodeConfig[StateManagerInnerConfig, None]):
    """Full configuration for State Manager node (no credentials needed)."""
    pass


class StateManagerNode(WorkflowNode):
    """
    State Manager workflow node.

    Loads persistent state from the database, merges with initial_state defaults,
    and outputs the combined state for downstream nodes to use. When connected
    to a Code node's state handle, the state can be mutated and automatically
    persisted after execution.
    """

    edit_examples = [
        "Set default state with counter initialized to 0 and items array",
        "Update default state to include processed_ids map for deduplication",
        "Reset default state values but keep persistence across executions",
        "Add timestamp field to state for tracking when state was last updated",
        "Include API rate limit tracker in default state configuration",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return StateManagerNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the State Manager node."""
        logger.info(f"[StateManagerNode] Executing node {self.node_id}")
        start_time = time.time()

        # Get config
        node_config = self.config
        default_state = {}
        if node_config and isinstance(node_config, StateManagerNodeConfig):
            default_state = node_config.config.state or {}

        try:
            # Load persisted state from database
            stored_state = await self._load_node_state()

            # Merge: default_state as defaults, stored_state overwrites
            state = {**default_state, **stored_state}

            timing_ms = (time.time() - start_time) * 1000

            logger.info(f"[StateManagerNode] Loaded state with {len(state)} keys (default: {len(default_state)}, stored: {len(stored_state)})")

            return {
                'type': 'state_manager',
                'status': 'success',
                'state': state,
                'timing_ms': round(timing_ms, 2),
                'timestamp': time.time()
            }

        except Exception as e:
            timing_ms = (time.time() - start_time) * 1000
            error_msg = str(e)
            logger.error(f"[StateManagerNode] Error loading state: {error_msg}")
            return {
                'type': 'state_manager',
                'status': 'error',
                'error': error_msg,
                'state': default_state,  # Fall back to default state on error
                'timing_ms': round(timing_ms, 2),
                'timestamp': time.time()
            }
