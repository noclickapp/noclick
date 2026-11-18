"""The reference generated from this package's source (scripts/gen_reference.py) documents every call."""

import importlib.util
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "gen_reference.py"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_reference", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _generator()


@lru_cache(maxsize=1)
def _reference():
    """The reference as generated from the source."""
    return json.loads(gen.render(gen.build()))


def _callables():
    """(label, entry) for every function and method the reference documents."""
    data = _reference()
    for page in data["pages"]:
        for item in page["items"]:
            if item["kind"] == "function":
                yield item["name"], item
            if item["kind"] not in ("class", "exception"):
                continue
            constructor = next((m for m in item["methods"] if m["kind"] == "constructor"), None)
            if constructor is not None:
                yield f"nc.{item['name']}", {**constructor, "usage": item["usage"] or constructor["usage"]}
            for method in item["methods"]:
                if method["kind"] != "constructor":
                    yield f"{item['name']}.{method['name']}", method
    for method in data["objects"]["methods"]:
        yield f"obj.{method['name']}", method


def test_every_documented_call_has_a_usage_example_that_calls_it():
    missing = []
    for label, entry in _callables():
        usage = entry["usage"]
        called = "[" if entry["name"] == "__getitem__" else label.split(".")[-1]
        if not usage or called not in usage:
            missing.append(label)
    assert missing == [], f"no Usage: section showing the call in: {missing}"


def test_designed_parameters_are_marked_and_their_calls_say_so():
    marked = {label: [p["name"] for p in entry["params"] if p.get("designed")] for label, entry in _callables()}
    marked = {label: names for label, names in marked.items() if names}
    assert marked["Agent.from_name"] == ["card", "machine"]
    assert marked["Volume.create"] == marked["Volume.from_name"] == ["region"]
    assert marked["PhoneNumber.answer_with"] == ["texts"]
    unsaid = [label for label, entry in _callables() if label in marked
              and "invite-only beta" not in (entry["doc"] + entry["usage"]).lower()]
    assert unsaid == [], f"designed parameters their docstrings don't mention: {unsaid}"


def test_every_call_that_returns_something_says_what():
    missing = [label for label, entry in _callables()
               if entry["kind"] != "constructor" and entry["returns"] not in (None, "None") and not entry["returns_doc"]]
    assert missing == [], f"no Returns: section in: {missing}"
