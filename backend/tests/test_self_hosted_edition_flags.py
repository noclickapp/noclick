"""Every shipped runtime must announce itself as the self-hosted edition.

`utils.edition.is_local_edition()` is an explicit flag on purpose — nothing
auto-detects "looks local", so a misconfigured cloud deployment fails loudly
instead of silently degrading. The cost of that choice is that anything which
ships the application has to set it, and for four months nothing did: `make
local` set it, so development worked, while every Docker path ran with the flag
unset. The in-process event relay and the cron scheduler are mounted behind it,
so a self-hosted install silently had no `/relay` and no scheduler — its cron
and polling triggers never fired — while `CRON_SCHEDULER_URL` was configured to
point at the route that was never mounted.

The frontend half is read at BUILD time (`app/lib/edition.ts`), so an image
built without it ships hosted-only UI: a Google sign-in button with no provider
behind it, the onboarding questionnaire, a credit balance.

The images are derived rather than listed. A list is what went stale here.
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
DOCKER = REPO / "docker"

# VITE_NOCLICK_LOCAL contains NOCLICK_LOCAL, so the backend flag needs a left edge.
BACKEND_FLAG = re.compile(r"(?<![A-Z_])NOCLICK_LOCAL=1\b")
FRONTEND_FLAG = re.compile(r"\bVITE_NOCLICK_LOCAL=1\b")


def _dockerfiles() -> list[pathlib.Path]:
    found = sorted(DOCKER.glob("*.Dockerfile"))
    assert found, f"no Dockerfiles under {DOCKER} — has the layout changed?"
    return found


def _ships_the_backend(text: str) -> bool:
    """A stage that copies the backend in is a stage that will run it. COPY
    takes flags (--chown, --from), and skipping over them is the difference
    between guarding an image and quietly skipping it."""
    return bool(re.search(r"^COPY\s+(?:--\S+\s+)*backend\b", text, re.M))


def _builds_the_bundle(text: str) -> bool:
    return "pnpm run build" in text


@pytest.mark.parametrize("path", _dockerfiles(), ids=lambda p: p.name)
def test_images_that_run_the_backend_enable_the_local_edition(path):
    text = path.read_text()
    if not _ships_the_backend(text):
        pytest.skip("does not run the backend")
    assert BACKEND_FLAG.search(text), (
        f"{path.name} runs the backend without NOCLICK_LOCAL=1. The event relay\n"
        f"and the cron scheduler are mounted behind utils.edition.is_local_edition(),\n"
        f"so this image would serve 404 at /relay and never fire a schedule."
    )


@pytest.mark.parametrize("path", _dockerfiles(), ids=lambda p: p.name)
def test_images_that_build_the_bundle_enable_the_local_edition(path):
    text = path.read_text()
    if not _builds_the_bundle(text):
        pytest.skip("does not build the frontend bundle")
    assert FRONTEND_FLAG.search(text), (
        f"{path.name} builds the browser bundle without VITE_NOCLICK_LOCAL=1.\n"
        f"The flag is compiled in, so the built image would ship hosted-only UI."
    )


def test_the_flag_still_means_what_the_images_set():
    """If the predicate is renamed, the images above go quietly stale."""
    import os

    from utils.edition import is_local_edition

    before = os.environ.get("NOCLICK_LOCAL")
    try:
        os.environ["NOCLICK_LOCAL"] = "1"
        assert is_local_edition() is True
        os.environ.pop("NOCLICK_LOCAL")
        assert is_local_edition() is False
    finally:
        if before is None:
            os.environ.pop("NOCLICK_LOCAL", None)
        else:
            os.environ["NOCLICK_LOCAL"] = before
