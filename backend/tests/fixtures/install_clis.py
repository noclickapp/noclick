"""Install the repository's CLI pins into an isolated directory for native tests.

Usage: python backend/tests/fixtures/install_clis.py /tmp/noclick-test-clis
Add the resulting bin directory to PATH. Requires Git, npm, and Node >=24.15.
"""
import json
from pathlib import Path
import shlex
import subprocess
import sys


def install(target: Path):
    pins = json.loads((Path(__file__).parents[2] / 'nodes/agent/config/_cli_models.json').read_text())
    target.mkdir(parents=True, exist_ok=True)
    bindir = target / 'bin'
    bindir.mkdir(exist_ok=True)
    packages = [f"{pins[k]['package']}@{pins[k]['version']}" for k in ('codex', 'claude_code', 'opencode', 'openclaw')]
    subprocess.run(['npm', 'install', '--prefix', str(target / 'npm'), '--no-audit', '--no-fund', *packages], check=True)
    for binary in ('codex', 'claude', 'opencode', 'openclaw'):
        path = bindir / binary
        if path.is_symlink():
            path.unlink()
        path.symlink_to(target / 'npm/node_modules/.bin' / binary)
    hermes = target / 'hermes'
    subprocess.run(['git', 'clone', '--depth', '1', '--branch', pins['hermes']['ref'],
                    'https://github.com/NousResearch/hermes-agent.git', str(hermes)], check=True)
    venv = target / 'venv'
    subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
    python = venv / 'bin/python'
    subprocess.run([str(python), '-m', 'pip', 'install', '-e', f'{hermes}[mcp,anthropic]', 'aiohttp==3.14.3'], check=True)
    wrapper = bindir / 'hermes'
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(str(python))} {shlex.quote(str(hermes / "hermes"))} "$@"\n')
    wrapper.chmod(0o755)
    print(f'CLI pins installed in {bindir}')


if __name__ == '__main__':
    install(Path(sys.argv[1]).resolve())
