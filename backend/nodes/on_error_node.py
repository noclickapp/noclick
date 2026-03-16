# On-error node — triggered when a workflow execution encounters an error.
# One per workflow. Its forward-reachable subgraph executes with error details
# as output, enabling error notifications (Slack, email, etc.).

import logging
from typing import Dict, Any, Optional, Type
from pydantic import BaseModel

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


class OnErrorConfig(BaseModel):
    """Configuration for the on-error node."""
    pass


class OnErrorNodeConfig(NodeConfig[OnErrorConfig, None]):
    """Full configuration for on-error node (no credentials)."""
    pass


class OnErrorNode(WorkflowNode):
    """
    On-error node — executes when a workflow encounters an error.

    One on-error node is allowed per workflow. When any node fails during
    execution, this node and its forward-reachable subgraph are executed
    with error details as output. This enables building error notification
    flows (e.g., Slack alerts, emails, logging).

    The on-error subgraph is excluded from normal workflow execution and
    only runs when an error occurs.
    """

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return OnErrorNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        # Return the error details injected by the execution handler.
        # These are available for downstream nodes to reference
        # (e.g., {{on-error-node-id.error}}, {{on-error-node-id.workflow_id}}).
        # _resolve_credentials nests config under a 'config' key, so check both levels.
        error_inputs = (
            self.node_data.get('config', {}).get('_error_inputs')
            or self.node_data.get('_error_inputs')
            or {}
        )
        return {
            'error': error_inputs.get('error', 'Unknown error'),
            'workflow_id': error_inputs.get('workflow_id', ''),
            'execution_id': error_inputs.get('execution_id', ''),
            'nodes_executed': error_inputs.get('nodes_executed', 0),
            'duration': error_inputs.get('duration', 0),
        }
