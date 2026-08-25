"""Edition detection for the self-hosted local build.

NOCLICK_LOCAL=1 selects the portable in-process integrations supplied with
this edition.
The flag is explicit — nothing auto-detects "looks local" — so a misconfigured
a non-local deployment fails loudly instead of silently changing behavior.
"""

import os


def is_local_edition() -> bool:
    return os.environ.get("NOCLICK_LOCAL") == "1"
