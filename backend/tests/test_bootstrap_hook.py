"""NOCLICK_BOOTSTRAP: how a deployment adds itself to the engine.

The engine ships publicly and must not name whatever is deploying it, so the
name lives in the environment. This pins the three answers that matter: unset
does nothing, a malformed value fails loudly, and a valid one runs before the
app exists.

The last property is the point. Backends and routes both register during
start-up; a hook that ran after assembly would leave the seams on their local
defaults and mount nothing, silently.
"""

import pytest

import server


def test_unset_is_a_no_op(monkeypatch):
    """The plain install. Nothing to import, nothing to fail."""
    monkeypatch.delenv("NOCLICK_BOOTSTRAP", raising=False)
    server._run_configured_bootstrap()


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_is_also_unset(monkeypatch, value):
    """What an env file or a PaaS dashboard produces for a variable nobody
    filled in."""
    monkeypatch.setenv("NOCLICK_BOOTSTRAP", value)
    server._run_configured_bootstrap()


@pytest.mark.parametrize("value", ["nomodule", "module:", ":function"])
def test_malformed_raises(monkeypatch, value):
    monkeypatch.setenv("NOCLICK_BOOTSTRAP", value)
    with pytest.raises(RuntimeError, match="module:function"):
        server._run_configured_bootstrap()


def test_a_missing_module_is_not_swallowed(monkeypatch):
    """A deployment that asked for a bootstrap and did not get one is
    misconfigured. Starting anyway would serve a system quietly missing
    whatever the bootstrap was for."""
    monkeypatch.setenv("NOCLICK_BOOTSTRAP", "noclick_no_such_module:go")
    with pytest.raises(ImportError):
        server._run_configured_bootstrap()


def test_it_calls_the_named_function(monkeypatch):
    import sys as _sys
    import types

    called = []

    probe = types.ModuleType("noclick_bootstrap_probe")
    probe.go = lambda: called.append(True)
    _sys.modules["noclick_bootstrap_probe"] = probe
    try:
        monkeypatch.setenv("NOCLICK_BOOTSTRAP", "noclick_bootstrap_probe:go")
        server._run_configured_bootstrap()
        assert called == [True]
    finally:
        _sys.modules.pop("noclick_bootstrap_probe", None)
