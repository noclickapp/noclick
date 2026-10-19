"""A failed local mount tells a person what failed, never the script's output."""

import pytest

from nodes.agent.git_mounts import _run_local, mount_failure_line
from nodes.core.base import FailureWithDiagnostics

TOKEN = "ghp_" + "s3cret" * 6


async def test_a_person_reads_why_and_the_output_stays_in_the_diagnostics():
    script = (f"echo 'remote: Repository not found.' >&2; "
              f"echo \"fatal: https://x-access-token:{TOKEN}@github.com/acme/web.git\" >&2; exit 128")
    with pytest.raises(FailureWithDiagnostics) as caught:
        await _run_local(script, "Local mount of acme/web", [TOKEN])

    assert str(caught.value) == ("Local mount of acme/web failed: "
                                 "the repository wasn't found, or its account can't read it")
    assert "Repository not found" in caught.value.diagnostics and "(exit 128)" in caught.value.diagnostics
    assert TOKEN not in caught.value.diagnostics


def test_anything_else_reads_as_its_exit_code():
    assert mount_failure_line("gh CLI auth", 2, f"error: unexpected {TOKEN}") == "gh CLI auth failed: exit 2"
