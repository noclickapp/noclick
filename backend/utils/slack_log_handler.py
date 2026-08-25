"""No-op compatibility hooks for managed log forwarding."""


def init_slack_log_handler() -> None:
    return None


def shutdown_slack_log_handler() -> None:
    return None
