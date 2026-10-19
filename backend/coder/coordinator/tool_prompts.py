"""The coordinator's tool descriptions as the engine ships them (pack ``coordinator_tools``, utils/prompts.py):
one plain line each. A deployment registers its own under the same name, with every part below and every key of
``DESCRIPTIONS`` (a tool's description) and ``PARAMETERS`` (``"tool.parameter"``: that parameter's)."""

from typing import Any, Dict, List

__all__ = [
    "DESCRIPTIONS", "PARAMETERS", "account_overview", "job_status", "cancel_job", "generate_video",
    "request_phone_number", "message_owner", "purchase_link", "purchase_link_in_credits", "purchase_links_next",
]

DESCRIPTIONS = {
    "list_credentials": "List the account's connections, without secrets.",
    "search_credential_tools": ("Search operations across connected accounts and load matching ones as tools; each "
                                "takes the credential_id of the account to act as."),
    "find_connections": "Find the connection types the account can connect, by service name.",
    "connect_credential": "Create a link for the owner to connect an account. Completion wakes you.",
    "credential_connection_status": "Check whether a connection link was completed.",
    "credential_operation_status": "Check a long-running operation by operation_id; pending is not success.",
    "request_credential_permissions": "Send the owner a link to review a connection's approval rules.",
    "credential_operations": "List a connection's operations, or one operation's argument schema.",
    "call_credential_operation": ("Run one operation with a connection. A restricted operation waits for the "
                                  "owner's approval."),
    "require_credential_approval": "Require the owner's approval for operations on a connection.",
    "lookup_credential_options": "Find valid ids for an operation's fields.",
    "read_attachment": "Read an attachment's text, a page at a time.",
    "schedule_alarm": "Schedule a message that wakes you later, once or on a cron schedule.",
    "list_alarms": "List the account's alarms.",
    "update_alarm": "Change a pending alarm's time and message.",
    "cancel_alarm": "Cancel an alarm.",
    "web_search": "Search the web; cite the URLs it returns.",
    "generate_image": "Make an image from a description; show it as ![caption](url).",
    "search_memories": "Search your memories by keywords.",
    "read_memory": "Read one memory in full.",
    "save_memory": "Save a new memory, or update one you read (pass memory_id and expected_version).",
    "forget_memory": "Forget a memory.",
    "search_history": "Search older messages in this conversation.",
    "list_workflows": "List the account's workflows.",
    "describe_workflow": "Describe a workflow: its nodes, wiring, triggers and credentials.",
    "find_agents": "Find the account's agents; returns the workflow_id and node_id message_agent takes.",
    "message_agent": "Send work to an agent; its reply arrives here later.",
    "request_build": "Ask the builder to create, change or publish a workflow, agent or interface.",
    "list_runs": "List a workflow's recent runs.",
    "get_run": "Read one run in detail.",
    "pause_workflow": "Switch a workflow's triggers off.",
    "resume_workflow": "Turn back on the triggers you paused.",
    "trash_workflow": "Move a workflow to the trash; confirm with the owner first.",
    "restore_workflow": "Bring a workflow back from the trash.",
    "find_phone_numbers": "Find phone numbers for sale in a country, with their prices.",
    "phone_number_request_status": "Read a phone number purchase request's status.",
    "set_email_address": "Choose or rename your own email address.",
    "auto_topup": "Read the account's auto top-up, or lower it or turn it off.",
    "request_upi_payment": "Ask the owner to pay a merchant by UPI, with the merchant's own payment details.",
    "connect_account": "Send a code to the email the owner gives, to connect it to this account.",
    "confirm_connect_code": "Check the code the owner received by email.",
    "set_followup_delivery": "Choose whether this completion notifies the owner and includes a call's recording.",
}

PARAMETERS = {
    "list_credentials.query": "Text in a connection's name, type or identity.",
    "schedule_alarm.delay_or_time": "A duration (5m, 2h), an ISO timestamp with a timezone, or a cron schedule.",
    "schedule_alarm.timezone_name": "The IANA timezone for a cron schedule.",
    "schedule_alarm.send_to_phone": "Also deliver it to the owner's phone.",
    "generate_image.model": "A model the owner named.",
    "generate_video.model": "A model the owner named.",
    "account_overview.section": "One section, or 'all'.",
    "list_workflows.query": "Optional filter.",
    "describe_workflow.focus": "Optional node id.",
    "find_agents.query": "Optional name or purpose.",
    "message_agent.message": "The instructions for the agent.",
    "message_agent.reply_to_job_id": "A previous job whose conversation to continue.",
    "request_build.instructions": "What to build or change.",
    "request_build.workflow_id": "The workflow to change; omit to create one.",
    "request_build.name": "A new workflow's name.",
    "request_build.send_to_phone": "Send the result to the owner's phone.",
    "request_build.publish": "Publish, rename or unpublish the interface.",
    "find_phone_numbers.country": "An ISO alpha-2 country code.",
    "find_phone_numbers.number_type": "The kind of number.",
    "find_phone_numbers.locality": "A city.",
    "find_phone_numbers.contains": "Digits the number contains.",
    "find_phone_numbers.features": "Calls only, or calls and texts.",
    "request_phone_number.purpose": "What the number is for.",
    "request_phone_number.phone_number": "A number find_phone_numbers returned.",
    "request_phone_number.country": "The number's country.",
    "request_phone_number.number_type": "The number's kind.",
    "message_owner.text": "The message.",
    "message_owner.link": "An optional URL.",
    "message_owner.subject": "The subject, for email.",
    "set_email_address.name": "The part before @.",
    "submit_feedback.workflow_id": "The workflow it happened in, if any.",
    "purchase_link.billing_period": "For a plan.",
    "purchase_link.amount_usd": "The dollars of funds to add.",
    "auto_topup.when_below_usd": "The new, lower line.",
    "auto_topup.add_usd": "The new, smaller amount.",
    "auto_topup.monthly_limit_usd": "The new, lower monthly limit.",
    "request_upi_payment.upi_link": "The merchant's upi://pay link, exactly as given.",
    "request_upi_payment.vpa": "Without a link: the merchant's UPI ID, exactly as given.",
    "request_upi_payment.payee_name": "Without a link: the merchant's business name.",
    "request_upi_payment.amount_inr": "Rupees, unless the link carries the amount.",
    "request_upi_payment.note": "What it pays for.",
}


def account_overview(*, platform: bool) -> str:
    """``platform``: the turn has a platform's tools, whose section the tool offers."""
    return "What needs attention in the account now: items for the owner, runs, agents and credential health."


def job_status(*, purchases: bool, upi: bool, platform: bool) -> str:
    """Which other kinds of job the turn can start (purchase links, UPI payment requests, platform jobs)."""
    return "Read the jobs you started and their results: one by job_id, or the recent ones."


def cancel_job(*, upi: bool) -> str:
    return "Cancel a job you started, where its kind can be cancelled."


def generate_video(*, model: str, seconds: int, resolution: str) -> str:
    return (f"Start a video from a description (defaults: {model}, {seconds}s, {resolution}). You are woken when "
            "it's ready.")


def request_phone_number(*, purchase_floor_usd: float) -> str:
    return "Prepare a phone number purchase and return a link for the owner to review and buy it."


def message_owner(*, has_email: bool) -> str:
    """``has_email``: the account has an email (else the email channel isn't offered)."""
    return "Message the owner outside this reply, on the channel they prefer ('auto': the one they last used)."


def purchase_link_in_credits(*, plans: List[Dict[str, Any]], topups: List[Dict[str, Any]], checkout_note: str) -> str:
    """For an account billed in credits: its ``plans`` and monthly credit ``topups``, with prices."""
    return ("A payment link for this account: a plan ("
            + ", ".join(f"{p['label']} ${p['monthly_usd']:g}/month" for p in plans)
            + ") or a monthly credit top-up. " + checkout_note)


def purchase_link(*, plans: List[Dict[str, Any]], funds: Dict[str, Any], checkout_note: str) -> str:
    """Its ``plans`` and the ``funds`` range (``min_usd``, ``max_usd``, ``presets_usd``), with prices."""
    return ("A payment link for this account: a plan ("
            + ", ".join(f"{p['label']} ${p['monthly_usd']:g}/month" for p in plans)
            + f") or funds for its balance, ${funds['min_usd']:,} to ${funds['max_usd']:,}. " + checkout_note)


def purchase_links_next(*, plan_and_topup: bool, by_size: bool) -> str:
    """What to do with the links a refusal returns. ``plan_and_topup``: both are needed; ``by_size``: top-ups."""
    return "Send these links with their prices; payment wakes you. purchase_link makes others."
