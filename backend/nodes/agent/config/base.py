"""
Base agent configuration fields shared across all model types.

All model-specific config classes inherit from BaseAgentFields to get
the common fields (system_prompt, message, temperature, conversation_key).
"""

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class BaseAgentFields(BaseModel):
    """Fields shared by all agent model types."""
    # Signals to the frontend that the AgentConfig discriminated union should
    # render as one flat merged form (no separate operation picker) — the `model` string
    # field, not `model_type`, is what the user picks. See NodeConfig.tsx.
    model_config = ConfigDict(json_schema_extra={"x-flatten-union": True})

    system_prompt: str = Field(
        default="You are a helpful assistant.",
        title="System Prompt",
        description="Instructions defining how the AI agent should behave",
        json_schema_extra={"ui:widget": "textarea"}
    )
    message: str = Field(
        min_length=1,
        title="Message",
        description="The task or question to send to the agent",
        json_schema_extra={
            "ui:widget": "textarea",
            "ui:help": "When a trigger is wired into this agent, the fired event is delivered alongside this message — write standing instructions here, not the event itself.",
        }
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        title="Temperature",
        description="Creativity level (0.0 = focused, 2.0 = creative)"
    )
    # One-shot per-turn payload from the chat composer (never persisted to the
    # saved node config — it rides the run override like `message`). Entries:
    # {url, name, mime_type, size_bytes, resource_id}. Normalized + composed
    # into the turn by AgentNode via nodes/agent/attachments.py.
    message_attachments: Optional[Any] = Field(
        default=None,
        title="Message Attachments",
        description="Files attached to this chat message (set by the chat composer, not manually).",
        json_schema_extra={"ui:hidden": True},
    )
    conversation_key: Optional[Any] = Field(
        default=None,
        title="Conversation Key",
        description="Unique key for tracking conversation history. Same key = same conversation. Channel triggers wired into the agent (Telegram, Slack, alarms) supply their chat/thread id automatically — only set this to override.",
        json_schema_extra={
            "type": "string",
            "ui:widget": "textarea",
            "ui:category": "Advanced",
            "ui:help": "When set, the agent maintains separate chat histories per key value. Use references like {{nodeId.field}} to pull from upstream data. A wired channel trigger's key takes priority when it fires.",
        }
    )
    # Gates the injected prompt_builder platform tool (nodes/agent/
    # platform_tools.py): lets the agent propose edits to its own workflow via
    # the AI builder (approval-gated in interactive chats, headless in
    # background runs). submit_feedback has no gate — it is always injected.
    enable_prompt_builder: str = Field(
        default="true",
        title="Allow Workflow Edits",
        description="Give this agent a prompt_builder tool to propose changes to this workflow via the AI builder.",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
            "ui:category": "Advanced",
            "ui:help": "In the interface chat, proposals ask for your approval before the builder runs. Background runs (triggers, schedules) apply edits headlessly.",
        }
    )
    # Gates the injected email_user platform tool (utils/agent_email.py): lets
    # the agent email the workflow owner when they're away (builder/credential
    # links, questions, failure reports). ON by default; the email's
    # unsubscribe link flips this flag to "false" for THIS node only.
    enable_email_updates: str = Field(
        default="true",
        title="Allow Email Updates",
        description="Give this agent an email_user tool to email you updates, questions, and links when you're away. Replying to the email talks back to the agent.",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
            "ui:category": "Advanced",
            "ui:help": "Emails come from a reply-able per-conversation address and carry a one-click unsubscribe scoped to this agent only. Capped per day and charged like the send-email node.",
        }
    )
    # Surfaces this agent as a fullscreen chat tab in the workflow's Interface tab,
    # making it easy to configure the model + chat with the agent without leaving
    # the editor. Rendered as a separate AgentChatBlock — see frontend.
    show_in_interface: str = Field(
        default="true",
        title="Show in Interface",
        description="Show this agent as a fullscreen chat in the Interface tab.",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
            "ui:category": "Advanced",
        }
    )


def infer_model_type(data: dict) -> dict:
    """
    Add model_type if missing (backward compat for existing workflows).

    Inspects the 'model' string to determine which config type to use.
    Called by Pydantic's discriminated union before validation.
    """
    if not isinstance(data, dict) or 'model_type' in data:
        return data

    model = str(data.get('model') or '').lower()

    if model == 'codex':
        data['model_type'] = 'codex'
    elif model == 'claude-code':
        data['model_type'] = 'claude_code'
    elif model == 'opencode':
        data['model_type'] = 'opencode'
    elif model == 'openclaw':
        data['model_type'] = 'openclaw'
    elif model == 'hermes':
        data['model_type'] = 'hermes_agent'
    elif 'kling' in model:
        data['model_type'] = 'kling'
    elif any(kw in model for kw in ['image', 'imagen', 'dall-e', 'dalle']):
        data['model_type'] = 'image'
    elif any(kw in model for kw in ['veo', 'sora', 'runwayml/']):
        data['model_type'] = 'video'
    else:
        data['model_type'] = 'llm'

    return data
