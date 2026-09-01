#!/usr/bin/env node
// `npx noclick` — the one-command install the README promises. A thin wrapper
// over the shell installer so there is exactly ONE install implementation;
// everything the script honors (NOCLICK_DIR, NOCLICK_REF, NOCLICK_NO_START, …)
// passes through the environment untouched. Published `noclick` versions
// before 0.1.3 were the SDK alone and had no executable at all — `npx noclick`
// died with "could not determine executable to run" on every fresh machine.
import { spawnSync } from 'node:child_process';

if (process.platform === 'win32') {
    console.error(
        'NoClick installs on Windows through WSL2 (which Docker Desktop uses anyway).\n' +
            'Open a WSL terminal and run:  curl -fsSL https://noclick.com/install.sh | sh'
    );
    process.exit(1);
}

const result = spawnSync('sh', ['-c', 'curl -fsSL https://noclick.com/install.sh | sh'], {
    stdio: 'inherit',
});
process.exit(result.status ?? 1);
