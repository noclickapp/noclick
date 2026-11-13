"""Harness drift is caught at the pins, before a user's thread finds it.

The engine's readers and writers were validated against ONE version of each
harness — fixtures in its record shapes here, and the real binary in the
Harness E2E. NoClick's pins move on their own (the daily refresh). This
test makes every move visible: a bumped pin fails until someone has re-run
both and re-declared the validated version, and the engine stays a
dependency-free package that ships into the sandboxes as files.
"""

from pathlib import Path

from nodes.agent import interchange as ic
from nodes.agent import session_interchange as si

BACKEND = Path(__file__).resolve().parents[1]

#: harness → the version the engine's format was validated against.
VALIDATED_HARNESS_VERSIONS = {
    "claude_code": "2.1.295",
    "codex": "0.162.0",
    "opencode": "1.18.35",
    "hermes_agent": "v2026.9.24",
    "openclaw": "2026.9.1",
}


#: harness → a newer version whose store the reader was checked against, from a real run's rows: a laptop runs
#: whatever it runs, and a move reads its session there. Writers stay on the pins above.
READ_ALSO = {
    "opencode": "2.2.5",
}


def test_newer_stores_read_are_declared_from_their_fixtures(tmp_path):
    from tests.test_session_interchange import CWD, OPENCODE2_SID, _opencode2_home

    home = _opencode2_home(tmp_path)
    thread = ic.read_thread(ic.StoreRef("opencode", home, Path(CWD), session_id=OPENCODE2_SID))
    assert {"opencode": thread.cli_version} == READ_ALSO, "re-capture the fixture from the version you declare"


def test_every_format_is_validated_against_the_pinned_harness():
    pins = si.harness_pins()
    assert set(VALIDATED_HARNESS_VERSIONS) == set(ic.FORMATS), "declare a validated version for every format, and only for formats"
    for harness, validated in VALIDATED_HARNESS_VERSIONS.items():
        assert pins[harness] == validated, (
            f"{harness}: NoClick now pins {pins[harness]} but the interchange format was validated against {validated}. "
            "Re-run tests/test_session_interchange.py against the new version's record shapes, re-run the Harness E2E "
            "(test_prod_thread_moves_between_harnesses), then re-declare VALIDATED_HARNESS_VERSIONS."
        )


def test_the_engine_has_no_third_party_dependency():
    requirements = (BACKEND.parent / "requirements.txt").read_text()
    assert "session-migrate" not in requirements
    for path in (BACKEND / "nodes" / "agent" / "interchange").rglob("*.py"):
        assert "session_migrate" not in path.read_text()


def test_interchange_version_is_recorded_in_every_verdict():
    assert ic.INTERCHANGE_VERSION and ic.INTERCHANGE_VERSION.strip().isdigit()
