"""What the engine records when nothing configures it: provider cost at list
price, one credit per dollar. A platform publishes its own numbers into the
environment before the module is imported (cloud.billing.register), so this is
checked in a fresh interpreter with those variables absent, then present."""

import os
import subprocess
from decimal import Decimal
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROBE = (
    "from decimal import Decimal; import billing.markup as m; "
    "print(m.CREDITS_PER_DOLLAR, m.CREDIT_STEP_DOLLARS, m.PLATFORM_MIN_MARKUP, "
    "m.round_up_to_credit_step(Decimal('0.0031')))"
)


def _probe(env_overrides):
    env = {k: v for k, v in os.environ.items() if k not in ("CREDITS_PER_DOLLAR", "PLATFORM_MARKUP")}
    env.update(env_overrides)
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=BACKEND, env=env, capture_output=True, text=True, check=True)
    return [Decimal(v) for v in out.stdout.split()]


def test_unconfigured_engine_counts_dollars_at_list_price():
    assert _probe({}) == [Decimal("1"), Decimal("0.01"), Decimal("1"), Decimal("0.01")]


def test_a_platform_publishes_its_conversion_and_markup():
    assert _probe({"CREDITS_PER_DOLLAR": "4", "PLATFORM_MARKUP": "3"}) == [
        Decimal("4"), Decimal("0.0025"), Decimal("3"), Decimal("0.005")
    ]


def test_work_attributed_to_a_product_sold_at_cost_carries_no_markup(monkeypatch):
    import contextvars

    from billing import markup
    from billing.usage_tracker import attribute_usage

    monkeypatch.setattr(markup, "PLATFORM_MIN_MARKUP", Decimal("3"))
    monkeypatch.setattr(markup, "_AT_COST", {"acme_api"})

    def attributed():
        attribute_usage(acme_api={"key_id": "k"})
        return (markup.current_markup(), markup.apply_platform_markup(Decimal("2"), False, "m"),
                markup.apply_ai_builder_markup(Decimal("2")), markup.apply_ai_testing_markup(Decimal("2")))

    assert contextvars.copy_context().run(attributed) == (Decimal("1"), Decimal("2"), Decimal("2"), Decimal("2"))
    # Work attributed to nothing, or to something else, keeps the deployment's markup.
    assert markup.current_markup() == Decimal("3")
    assert contextvars.copy_context().run(lambda: (attribute_usage(other=1), markup.current_markup())[1]) == (
        Decimal("3"))
    assert markup.at_cost({"acme_api": {}}) and not markup.at_cost({"other": {}})
