"""Translation drift is caught at the pins, before a user's thread finds it.

The translator (``session-migrate``) validates each harness at ONE version
and NoClick pins each harness at its own; the two move independently (the
daily refresh bumps ours, upstream releases weekly). This suite makes every
move visible: the translator pin is one number across ``requirements.txt``,
the engine and the installed package (the hosted sandbox images are pinned in
``cloud/tests``); and the lag between what the translator validated and what
NoClick runs is DECLARED here, so a bump on
either side fails until someone has re-run the fixtures (and, for a real
binary, the harness E2E) and re-declared the lag.
"""

from pathlib import Path

import session_migrate
from session_migrate.formats import claude, codex, hermes, opencode

from nodes.agent import session_interchange as si

BACKEND = Path(__file__).resolve().parents[1]

#: harness → (NoClick's pin, the version the translator validated, consequence).
#: ``warning``: the translator reads by record shape; ``tests/test_session_interchange.py``
#: carries fixtures in the pinned shape. ``blocked``: the translator drives the
#: harness CLI and refuses other versions; the pair falls back (loudly) until
#: session-migrate catches up. ``unaddressable``: see ``si.UNADDRESSABLE``.
KNOWN_TRANSLATOR_LAG = {
    "claude_code": ("2.1.261", "2.1.209", "warning"),
    "codex": ("0.153.4", "0.144.4", "warning"),
    "opencode": ("1.18.29", "1.17.20", "blocked"),
    "hermes_agent": ("v2026.8.31", "v2026.8.27", "unaddressable"),
}


def test_translator_pin_is_one_number_everywhere():
    assert session_migrate.__version__ == si.TRANSLATOR_VERSION
    requirements = (BACKEND.parent / "requirements.txt").read_text()
    assert si.translator_requirement() in requirements.splitlines()


def test_translator_lag_is_declared_for_every_harness_pin():
    ours = si.harness_pins()
    validated = {
        "claude_code": claude.PINNED_CLAUDE_VERSION,
        "codex": codex.PINNED_CODEX_VERSION,
        "opencode": opencode.PINNED_OPENCODE_VERSION,
        "hermes_agent": hermes.PINNED_HERMES_RELEASE_TAG,
    }
    for harness, (declared_ours, declared_theirs, consequence) in KNOWN_TRANSLATOR_LAG.items():
        assert (ours[harness], validated[harness]) == (declared_ours, declared_theirs), (
            f"{harness}: NoClick pins {ours[harness]} and session-migrate {si.TRANSLATOR_VERSION} validated "
            f"{validated[harness]}, but KNOWN_TRANSLATOR_LAG declares {(declared_ours, declared_theirs)}. "
            "A pin moved: re-run tests/test_session_interchange.py (fixtures in the pinned record shape) and the "
            "harness E2E, then re-declare the lag here — or bump session-migrate so it validates the new pin."
        )
    # The engine's verdict on each pair must agree with the declaration.
    blocked = si.pair_support("opencode", "claude_code", pins=ours)
    if KNOWN_TRANSLATOR_LAG["opencode"][2] == "blocked":
        assert blocked and blocked[0] == "translator_pin_mismatch"
    else:
        assert blocked is None
    assert si.pair_support("claude_code", "codex", pins=ours) is None


def test_openclaw_has_no_translator_adapter_yet():
    assert "openclaw" not in si.HARNESS_FORMATS
    assert si.pair_support("openclaw", "codex")[0] == "no_adapter"
