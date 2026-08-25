"""
Alarm node for workflow automation.

Connects to AI Agent nodes via top→bottom handle (like tool nodes).
Provides alarm management tools that let agents schedule countdown timers,
one-time alarms, recurring cron schedules, and manage existing alarms
(list, cancel, update). When an alarm fires, the connected agent is
re-invoked with the stored message.
"""

import logging
import uuid as uuid_module
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Alarm Configuration
# ============================================================================

class AlarmConfig(BaseModel):
    """Alarm config with viewer widget for inspecting active alarms."""
    active_alarms: Optional[str] = Field(
        default=None,
        title="Active Alarms",
        json_schema_extra={
            "ui:widget": "alarm_viewer",
        }
    )


class AlarmNodeConfig(NodeConfig[AlarmConfig, None]):
    """Full configuration for Alarm node (no credentials needed)."""
    pass


# ============================================================================
# Tool Definition Constants
# ============================================================================

# --- schedule_alarm ---
SCHEDULE_ALARM_TOOL_NAME = "schedule_alarm"
SCHEDULE_ALARM_TOOL_DESCRIPTION = (
    "Schedule an alarm to wake you up later with a message. Supports three modes:\n"
    "- countdown: fires after a delay (e.g., '30s', '5m', '2h', '1d')\n"
    "- datetime: fires at a specific ISO 8601 timestamp (e.g., '2026-03-07T10:00:00Z')\n"
    "- cron: fires on a recurring schedule (standard cron expression, e.g., '0 9 * * 1')\n\n"
    "Include a descriptive message — you'll receive it when the alarm fires as context "
    "for what you should do."
)
SCHEDULE_ALARM_PARAMETERS: List[Dict[str, Any]] = [
    {
        "name": "alarm_type",
        "type": "string",
        "description": "One of: countdown, datetime, cron",
        "required": True,
    },
    {
        "name": "delay_or_time",
        "type": "string",
        "description": (
            "For countdown: duration like '30s', '5m', '2h', '1d'. "
            "For datetime: ISO 8601 timestamp. "
            "For cron: standard cron expression."
        ),
        "required": True,
    },
    {
        "name": "message",
        "type": "string",
        "description": (
            "Message to include when the alarm fires. This will be sent back "
            "as context for your next invocation."
        ),
        "required": True,
    },
]

# --- list_alarms ---
LIST_ALARMS_TOOL_NAME = "list_alarms"
LIST_ALARMS_TOOL_DESCRIPTION = (
    "List all active alarms and scheduled tasks for this workflow. "
    "Returns schedule IDs, types, next run times, messages, and enabled status. "
    "Use this to find schedule_ids before cancelling or updating alarms."
)
LIST_ALARMS_PARAMETERS: List[Dict[str, Any]] = []

# --- cancel_alarm ---
CANCEL_ALARM_TOOL_NAME = "cancel_alarm"
CANCEL_ALARM_TOOL_DESCRIPTION = (
    "Cancel (delete) an alarm by its schedule_id. "
    "Use list_alarms first to find the schedule_id of the alarm to cancel."
)
CANCEL_ALARM_PARAMETERS: List[Dict[str, Any]] = [
    {
        "name": "schedule_id",
        "type": "string",
        "description": "The schedule ID of the alarm to cancel (from list_alarms).",
        "required": True,
    },
]

# --- update_alarm ---
UPDATE_ALARM_TOOL_NAME = "update_alarm"
UPDATE_ALARM_TOOL_DESCRIPTION = (
    "Update an existing alarm. Can enable/disable it or change its message. "
    "Use list_alarms first to find the schedule_id."
)
UPDATE_ALARM_PARAMETERS: List[Dict[str, Any]] = [
    {
        "name": "schedule_id",
        "type": "string",
        "description": "The schedule ID of the alarm to update (from list_alarms).",
        "required": True,
    },
    {
        "name": "enabled",
        "type": "string",
        "description": "Set to 'true' to enable or 'false' to disable the alarm.",
        "required": False,
    },
    {
        "name": "message",
        "type": "string",
        "description": "New message for the alarm (delivered when it fires).",
        "required": False,
    },
]


# ============================================================================
# Tool Definition Helpers
# ============================================================================

def _make_tool_def(name: str, description: str, parameters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a single alarm tool definition dict."""
    return {
        'type': 'tool_definition',
        'tool_type': 'alarm',
        'tool_name': name,
        'tool_description': description,
        'parameters': parameters,
    }


def get_all_tool_definitions() -> List[Dict[str, Any]]:
    """Return all alarm tool definitions as a list."""
    return [
        _make_tool_def(SCHEDULE_ALARM_TOOL_NAME, SCHEDULE_ALARM_TOOL_DESCRIPTION, SCHEDULE_ALARM_PARAMETERS),
        _make_tool_def(LIST_ALARMS_TOOL_NAME, LIST_ALARMS_TOOL_DESCRIPTION, LIST_ALARMS_PARAMETERS),
        _make_tool_def(CANCEL_ALARM_TOOL_NAME, CANCEL_ALARM_TOOL_DESCRIPTION, CANCEL_ALARM_PARAMETERS),
        _make_tool_def(UPDATE_ALARM_TOOL_NAME, UPDATE_ALARM_TOOL_DESCRIPTION, UPDATE_ALARM_PARAMETERS),
    ]


# ============================================================================
# Alarm Node Implementation
# ============================================================================

class AlarmNode(WorkflowNode):
    """
    Alarm node for scheduling and managing agent wake-ups.

    Connects to AI agent nodes via top→bottom handle edges (same pattern as tool nodes).
    During normal workflow execution, returns alarm_tool_definitions with 4 tools:
    schedule_alarm, list_alarms, cancel_alarm, update_alarm.

    When an alarm fires via webhook, the webhook route sets _triggerPayload on this
    node with type='alarm_trigger' + embedded tool_definitions; the execution handler
    short-circuits it into the node output. The agent picks tool definitions out of
    that output (_collect_tool_definitions) and receives the wake-up message +
    conversation_key via the generalized trigger-event path (resolve_agent_event).
    """

    edit_examples = [
        "Test schedule_alarm countdown timer",
        "Check list_alarms to see scheduled tasks",
        "Cancel an alarm by schedule_id",
        "Update alarm message before it fires",
        "Set up recurring cron schedule",
        "Create alarm for specific datetime",
        "Disable and re-enable existing alarm",
    ]

    @classmethod
    def get_config_model(cls) -> type:
        """Get Pydantic config model for Alarm node."""
        return AlarmNodeConfig

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Alarm fire → the wake-up message + the conversation key captured at
        scheduling time, so the agent resumes the conversation that set the
        alarm."""
        message = output.get("message")
        if not message:
            return None
        return {
            "text": message,
            "conversation_key": output.get("conversation_key"),
        }

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: uuid_module.UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Load active alarms for this alarm node.

        Returns all alarm-source schedules associated with this node,
        optionally filtered by conversation_key from context.
        """
        if field_name != 'active_alarms':
            return {'value': None}

        from utils.cron_scheduler_client import list_schedules

        result = await list_schedules(workflow_id=str(workflow_id))
        if isinstance(result, dict) and 'error' in result:
            return {'value': {'error': result['error'], 'alarms': [], 'count': 0}}
        if not isinstance(result, list):
            return {'value': {'error': 'Unexpected response from scheduler', 'alarms': [], 'count': 0}}

        # Optional conversation_key filter from frontend context
        filter_ck = (context or {}).get('conversation_key')

        alarms = []
        for schedule in result:
            payload = schedule.get('payload') or {}
            if payload.get('source') != 'alarm':
                continue
            if payload.get('alarm_node_id') != node_id:
                continue
            if filter_ck and payload.get('conversation_key') != filter_ck:
                continue
            alarms.append({
                'schedule_id': schedule.get('id'),
                'type': 'one-time' if schedule.get('cron_expression') == '__run_at__' else 'cron',
                'enabled': bool(schedule.get('enabled', 1)),
                'next_run': schedule.get('next_run_at'),
                'created_at': schedule.get('created_at'),
                'message': payload.get('message', ''),
                'conversation_key': payload.get('conversation_key'),
            })

        return {'value': {'alarms': alarms, 'count': len(alarms)}}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return all alarm tool definitions.

        This is called during normal workflow execution (topological order).
        When an alarm fires, mockedOutput is set instead, so execute() is skipped.
        """
        return {
            'type': 'alarm_tool_definitions',
            'tools': get_all_tool_definitions(),
        }
