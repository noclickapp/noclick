"""The no-verdict outcome of a trigger registration attempt.

Lives in utils, not nodes.core.webhook_subscriptions (which applies it), so leaf
provider clients like utils.meta_subscriptions can raise it without importing
the node package.
"""


class RegistrationUnverified(ValueError):
    """An attempt that reached no verdict: the provider was down or
    throttling, the transport failed, another registration held the lock, or a
    write was accepted but could not be read back. It says nothing about a
    registration already on record, which stands."""
