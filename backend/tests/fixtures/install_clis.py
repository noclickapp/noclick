"""Install the repository's CLI pins into an isolated directory for native tests.

Usage: python backend/tests/fixtures/install_clis.py /tmp/noclick-test-clis
Add the resulting bin directory to PATH. Requires Git, npm, and Node 22 or 24.
"""
import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

HERMES_REPO = 'https://github.com/NousResearch/hermes-agent.git'


def github_git_env(token: str | None) -> dict[str, str]:
    """Git environment that authenticates github.com clones with an Actions token.

    Anonymous git-over-HTTPS from shared CI runners gets HTTP 429 from GitHub.
    The header rides GIT_CONFIG_* rather than the URL or argv, so a failed
    clone's CalledProcessError (which prints the command) cannot leak it.
    """
    if not token:
        return {}
    basic = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
    return {
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': 'http.https://github.com/.extraheader',
        'GIT_CONFIG_VALUE_0': f'AUTHORIZATION: basic {basic}',
    }


def clone_hermes(ref: str, dest: Path, token: str | None, attempts: int = 3,
                 sleep=time.sleep) -> None:
    """Clone the pinned hermes-agent tag, or reuse a checkout CI restored from cache.

    GitHub load-sheds this repository's git backend under heavy traffic (HTTP 429
    for every client, authenticated or not), so a warm cache never clones and a
    cold one retries briefly before giving up.
    """
    if (dest / '.git').exists():
        print(f'Reusing hermes-agent checkout at {dest}')
        return
    env = {**os.environ, **github_git_env(token)}
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(['git', 'clone', '--depth', '1', '--branch', ref, HERMES_REPO, str(dest)],
                           check=True, env=env)
            return
        except subprocess.CalledProcessError:
            shutil.rmtree(dest, ignore_errors=True)
            if attempt == attempts:
                raise
            sleep(20 * attempt)


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
    clone_hermes(pins['hermes']['ref'], hermes, os.environ.get('GITHUB_TOKEN'))
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
