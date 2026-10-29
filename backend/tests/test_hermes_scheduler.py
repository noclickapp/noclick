"""Hermes's own scheduler never fires in a gateway NoClick runs: its config names a scheduler that fires nothing, a
plugin under its home provides it, and the tool that would schedule on it is withheld."""
import abc
import threading
import types
from types import SimpleNamespace

import pytest
import yaml

from nodes.agent.hermes_scheduler import CRON_CONFIG, CRON_PROVIDER, WITHHELD_TOOLSETS, home_files


@pytest.mark.parametrize('persistent', [True, False])
def test_the_local_edition_runs_no_hermes_scheduler(tmp_path, monkeypatch, persistent):
    from nodes.agent import local_harness

    monkeypatch.setattr(local_harness, '_require_binary', lambda name, hint: name)
    config = SimpleNamespace(hermes_agent_model='anthropic/claude-sonnet-4-5', message='hi', system_prompt='')
    local_harness._build_command('hermes_agent', config, tmp_path, None, persistent=persistent)
    home = tmp_path / '.hermes'
    written = yaml.safe_load((home / 'config.yaml').read_text())
    assert written['cron'] == {'provider': CRON_PROVIDER} == yaml.safe_load(CRON_CONFIG)['cron']
    assert {'messaging', 'gateway', 'cronjob'} <= set(written['agent']['disabled_toolsets'])
    assert WITHHELD_TOOLSETS == ('cronjob',)
    for name, text in home_files().items():
        assert (home / name).read_text() == text


def test_the_scheduler_it_names_fires_nothing(monkeypatch):
    """The plugin against Hermes's scheduler contract (``cron.scheduler_provider.CronScheduler`` as of 2026.9.24: an
    abstract ``name`` property and ``start``, found through ``register(ctx)``): it registers one scheduler, by the
    name the config gives, whose ``start`` returns at once, so the gateway's ticker thread fires nothing."""

    class CronScheduler(abc.ABC):
        @property
        @abc.abstractmethod
        def name(self): ...

        @abc.abstractmethod
        def start(self, stop_event, *, adapters=None, loop=None, interval=60): ...

    provider_module = types.ModuleType('cron.scheduler_provider')
    provider_module.CronScheduler = CronScheduler
    monkeypatch.setitem(__import__('sys').modules, 'cron', types.ModuleType('cron'))
    monkeypatch.setitem(__import__('sys').modules, 'cron.scheduler_provider', provider_module)

    (source,) = home_files().values()
    plugin = {}
    exec(compile(source, f'plugins/{CRON_PROVIDER}/__init__.py', 'exec'), plugin)
    registered = []
    plugin['register'](SimpleNamespace(register_cron_scheduler=registered.append))
    (scheduler,) = registered
    assert isinstance(scheduler, CronScheduler) and scheduler.name == CRON_PROVIDER
    assert list(home_files()) == [f'plugins/{CRON_PROVIDER}/__init__.py']
    ticker = threading.Thread(target=scheduler.start, args=(threading.Event(),), kwargs={'adapters': {}, 'loop': None})
    ticker.start()
    ticker.join(timeout=1)
    assert not ticker.is_alive()
