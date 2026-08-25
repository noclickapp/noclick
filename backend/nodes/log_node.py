"""
Log node for workflow activity monitoring.

A lightweight fire-and-forget node that writes a log entry visible in the Feed's
Activity tab. Useful for tracking what workflows are doing ("Posted to Twitter",
"Sent 12 emails", etc.) without requiring human approval.
"""

import logging
from typing import Dict, Any, Optional, Type, List
from enum import Enum

from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class LogInnerConfig(BaseModel):
    """Configuration for the log node."""

    message: str = Field(
        ...,
        title="Message",
        description="Log message. Supports references like {{node.field}}.",
        json_schema_extra={
            "placeholder": "Posted {{twitter.tweet_url}} to Twitter",
            "ui:widget": "textarea",
            "ui:rows": 3,
        },
    )

    level: str = Field(
        default="info",
        title="Level",
        description="Log level for visual styling in the activity feed",
        json_schema_extra={
            "enum": ["info", "success", "warning", "error"],
            "enumNames": ["Info", "Success", "Warning", "Error"],
            "x-enum-searchable": True,
        },
    )


class LogNodeConfig(NodeConfig[LogInnerConfig, None]):
    """Full configuration for log node (no credentials needed)."""
    pass


class LogNode(WorkflowNode):
    """
    Activity log node — writes a message to the activity feed.

    The message is stored in the activity_logs table and emitted as a socket
    event so it appears in the Feed's Activity tab in real time.
    """

    edit_examples = [
        "Change level to success and update message for completion milestone",
        "Log error details with level=error when upstream node fails",
        "Update message to show item count and reference {{http.total_processed}}",
        "Set level to warning when rate limit detected in response",
        "Log successful API call with URL and status code reference",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return LogNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[LogNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, LogNodeConfig):
            raise ValueError(f"[LogNode] Configuration required for node {self.node_id}")

        config = node_config.config
        message = config.message or ""
        level = config.level if config.level in ("info", "success", "warning", "error") else "info"

        # Persist to activity_logs table
        if self.execution_id:
            try:
                from utils.database_pool import get_native_pool
                await get_native_pool().execute("""
                    INSERT INTO activity_logs
                        (workflow_id, execution_id, node_id, user_id, organization_id, message, level)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                    self.workflow_id, self.execution_id, self.node_id,
                    self.user_id, self.organization_id,
                    message, level,
                )
            except Exception as e:
                logger.warning(f"[LogNode] Failed to persist activity log: {e}")

        # Emit real-time socket event
        if self.sio and self.sid:
            try:
                from wss.sender import send_event
                from wss.sender.events import ActivityLogCreatedEvent
                await send_event(self.sio, self.sid, ActivityLogCreatedEvent(
                    workflow_id=self.workflow_id or "",
                    execution_id=self.execution_id or "",
                    node_id=self.node_id,
                    message=message,
                    level=level,
                ))
            except Exception as e:
                logger.warning(f"[LogNode] Failed to emit activity event: {e}")

        output = {
            "message": message,
            "level": level,
            "logged": True,
        }

        await self.emit(output)
        return output
