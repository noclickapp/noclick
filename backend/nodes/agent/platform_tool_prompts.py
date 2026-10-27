"""What agents are told about the platform tools, as the engine ships it (pack ``agent_platform_tools``,
utils/prompts.py): one plain line per tool and short per-turn notes. A deployment registers its own under the same
name, with every part below and every key of ``DESCRIPTIONS`` (a tool's description) and ``PARAMETERS``
(``"tool.parameter"``: that parameter's)."""

from typing import Any, Dict, List

__all__ = [
    "DESCRIPTIONS", "PARAMETERS", "platform_tools_note", "builder_anchor", "presence_note", "builder_update",
    "builder_updates", "ADDED_NOTES", "NOCLICK_NOTES",
]

DESCRIPTIONS = {
    "tell_parent": "Tell the agent that gave you your task something now, without stopping.",
    "wake_me": ("Take a turn in this conversation later: at a time, after some minutes, when an operation finishes, "
                "or on a cron schedule. Your note is what you'll be told."),
    "list_wakeups": "List the wake-ups set in this conversation that haven't come due.",
    "cancel_wakeup": "Cancel a wake-up set in this conversation.",
    "request_connection": "Ask the user to connect an account you need; returns a link to share with them.",
    "message_coordinator": "Send a message to the account's coordinator; it acts on it later.",
    "submit_feedback": "Report a platform bug: a platform tool that failed or returned a wrong result.",
    "prompt_builder": "Ask the workflow builder to change this workflow, such as wiring a new integration to you.",
    "describe_workflow": "Describe the workflow you are in: its nodes, wiring, triggers and your tools.",
    "builder_respond": "Answer the workflow builder's pending questions, by input id.",
    "email_user": "Email the workflow owner; their reply comes back to you.",
}

PARAMETERS = {
    "tell_parent.message": "What it should hear.",
    "wake_me.note": "What you'll be told when you wake.",
    "wake_me.at": "An ISO 8601 time.",
    "wake_me.after_minutes": "Minutes from now.",
    "wake_me.operation_id": "Wake when this operation finishes.",
    "wake_me.operation_ids": "Wake once, when the last of these operations finishes.",
    "wake_me.every": "A five-field cron schedule.",
    "wake_me.wakeup_id": "A wake-up of yours to change instead of setting a new one.",
    "wake_me.conversation": "Another of your own conversations to set it in (or change it in) instead of this one.",
    "list_wakeups.conversation": "Another of your own conversations to list instead of this one.",
    "cancel_wakeup.wakeup_id": "The wake-up's id.",
    "cancel_wakeup.conversation": "The conversation it was set in, when not this one.",
    "request_connection.integration": "The service, e.g. gmail.",
    "request_connection.operations": "The operations you need (omit for all).",
    "request_connection.name": "A short name for the connection.",
    "request_connection.reason": "Why, shown to the user.",
    "message_coordinator.message": "The message.",
    "submit_feedback.feedback": "What you did, what happened and what you expected.",
    "submit_feedback.issue_key": "A snake_case key for the root cause, the same each time it recurs.",
    "prompt_builder.prompt": "The change to make.",
    "describe_workflow.focus": "A node id to focus on (defaults to you).",
    "builder_respond.answers": "Input id to answer.",
    "builder_respond.message": "An optional free-form reply.",
    "email_user.subject": "The subject.",
    "email_user.body": "The message.",
}


def platform_tools_note(*, prompt_builder: bool, email: bool) -> str:
    """Steering for CLI harnesses: ``prompt_builder`` and ``email`` say whether those tools are offered this turn;
    submit_feedback always is."""
    return (("Gain integrations with prompt_builder, never by installing software in the sandbox. "
             if prompt_builder else "")
            + ("Use email_user to reach the owner when they are away. " if email else "")
            + "Use submit_feedback only for a platform tool that failed or returned a wrong result.")


def builder_anchor(node_id: str) -> str:
    """Added to a prompt_builder request so the builder changes the agent that asked."""
    return f"(Requested by the agent node '{node_id}': apply the change to that agent.)"


def presence_note(presence: str) -> str:
    """``presence``: whether the workflow owner is in the app (utils/user_presence)."""
    return f"--- Platform note ---\nThe workflow owner is {presence}. When they are away, use email_user to reach them."


def builder_update(kind: str, payload: Dict[str, Any]) -> str:
    """One line for a builder outcome event: ``builder_decision`` (a proposal approved or dismissed), ``builder_ask``
    (a run waiting on ``inputs`` or ``questions``, answered at ``bridge_url``) or ``builder_result``."""
    if kind == "builder_decision":
        verdict = "approved" if payload.get("decision") == "approved" else "dismissed"
        return f"- Your builder proposal {payload.get('proposal_id')} was {verdict}."
    if kind == "builder_ask":
        asks = ([f"[{i.get('id')}] {i.get('label')}" for i in payload.get("inputs") or []]
                or payload.get("questions") or ["more input"])
        return (f"- The builder is waiting on: {'; '.join(asks)}. Answer what you can with builder_respond; the "
                f"owner can answer the rest at {payload.get('bridge_url')}")
    return f"- The builder finished: {payload.get('summary')}"


def builder_updates(lines: List[str]) -> str:
    return "--- Platform note ---\nBuilder updates since your last turn:\n" + "\n".join(lines)


# Headed "--- Platform note ---": the notes added since the agent's last turn (a platform's ``add_note``).
ADDED_NOTES = "Added to this conversation since your last turn:"
# Headed "--- From NoClick ---": the private ones among them, the platform's own word, which no one else sees.
NOCLICK_NOTES = "NoClick's own word to you, which only you see: take it as fact."
