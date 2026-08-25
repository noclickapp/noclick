#!/usr/bin/env node
// `npx noclick` — run a NoClick instance on this machine.
//
// The whole stack lives in a compose file in the repository, so this is a
// launcher rather than a runtime: it fetches the source, generates the secrets
// that must be unique to an installation, and drives Docker. Nothing it does is
// unavailable by hand — `noclick where` prints the directory, and everything
// there is an ordinary git checkout and an ordinary compose project.
//
// Node 18+, no dependencies.

import { spawnSync } from 'node:child_process';
import { createHmac, randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline/promises';

const REPO = process.env.NOCLICK_REPO || 'https://github.com/noclickapp/noclick.git';
const REF = process.env.NOCLICK_REF || 'main';
const DIR = process.env.NOCLICK_DIR || join(homedir(), 'noclick');

const E = '';
const bold = (s) => `${E}[1m${s}${E}[0m`;
const dim = (s) => `${E}[2m${s}${E}[0m`;
const red = (s) => `${E}[31m${s}${E}[0m`;
const green = (s) => `${E}[32m${s}${E}[0m`;

const say = (msg) => console.log(`${bold('→')} ${msg}`);
function die(msg) {
    console.error(red(msg));
    process.exit(1);
}

function run(cmd, args, opts = {}) {
    return spawnSync(cmd, args, { stdio: 'inherit', ...opts });
}
function capture(cmd, args) {
    const r = spawnSync(cmd, args, { encoding: 'utf8' });
    return r.status === 0 ? (r.stdout || '').trim() : null;
}
const have = (cmd) => capture(cmd, ['--version']) !== null;

// ── Prerequisites ────────────────────────────────────────────────────────────

function requireDocker() {
    if (!have('docker')) {
        die(
            'Docker is required.\n' +
            '  Linux:   curl -fsSL https://get.docker.com | sh\n' +
            '  macOS:   https://docs.docker.com/desktop/install/mac-install/\n' +
            '  Windows: https://docs.docker.com/desktop/install/windows-install/',
        );
    }
    if (spawnSync('docker', ['info'], { stdio: 'ignore' }).status !== 0) {
        die(
            'Docker is installed but not running, or this user cannot reach it.\n' +
            '  Start Docker Desktop, or add yourself to the docker group:\n' +
            '    sudo usermod -aG docker "$USER"',
        );
    }
    warnIfDockerMemoryIsTight();
    if (spawnSync('docker', ['compose', 'version'], { stdio: 'ignore' }).status === 0) {
        return ['docker', ['compose']];
    }
    if (have('docker-compose')) return ['docker-compose', []];
    die('Docker Compose v2 is required — https://docs.docker.com/compose/install/');
}

// The frontend's production bundle is the memory high-water mark of the build:
// Node alone is given a 4 GiB heap, and whatever is already running shares the
// same limit. Below about 8 GiB the build spends twenty minutes reaching
// "ResourceExhausted: cannot allocate memory", which names neither the cause nor
// the fix. Warn rather than refuse — this is a heuristic, and a machine that
// disagrees should be allowed to try.
function warnIfDockerMemoryIsTight() {
    const raw = capture('docker', ['info', '--format', '{{.MemTotal}}']);
    const bytes = Number(raw);
    if (!Number.isFinite(bytes) || bytes <= 0) return;
    const gib = bytes / 1024 ** 3;
    if (gib >= 8) return;
    console.warn(
        `\n  Warning: Docker is limited to ${gib.toFixed(1)} GiB, and building the frontend\n` +
        '  wants about 8 GiB. If it stops at "cannot allocate memory", that is\n' +
        "  why: raise Docker's memory limit and run this again.\n",
    );
}

function compose(args, opts = {}) {
    const [cmd, base] = requireDocker();
    return run(cmd, [...base, ...args], { cwd: DIR, ...opts });
}

// ── Source ───────────────────────────────────────────────────────────────────

function ensureSource() {
    if (existsSync(join(DIR, '.git'))) return;
    if (existsSync(DIR) && readdirSync(DIR).length > 0) {
        die(`${DIR} already exists and is not a NoClick checkout.\n  Set NOCLICK_DIR to somewhere else.`);
    }
    if (!have('git')) die('git is required to fetch the source.');
    say(`Fetching NoClick into ${DIR}`);
    mkdirSync(DIR, { recursive: true });
    if (run('git', ['clone', '--quiet', '--depth', '1', '--branch', REF, REPO, DIR]).status !== 0) {
        die(`Could not clone ${REPO} (${REF}).`);
    }
}

function updateSource() {
    if (!existsSync(join(DIR, '.git'))) return ensureSource();
    say(`Updating ${DIR}`);
    if (run('git', ['-C', DIR, 'fetch', '--quiet', 'origin', REF]).status !== 0) {
        die(`Could not reach ${REPO}.`);
    }
    // Reset rather than merge: local edits to tracked files are not a supported
    // upgrade path, and a half-merged tree is worse than a clean one. .env is
    // untracked and survives.
    run('git', ['-C', DIR, 'checkout', '--quiet', '--force', 'FETCH_HEAD']);
}

// ── Configuration ────────────────────────────────────────────────────────────

const b64url = (buf) => buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
// Alphanumeric, so the value survives every .env, YAML and URL context it lands in.
const token = (len) => randomBytes(len * 2).toString('base64').replace(/[^A-Za-z0-9]/g, '').slice(0, len);
// Fernet wants 32 bytes as url-safe base64 — padding included, unlike a JWT segment.
const fernetKey = () => randomBytes(32).toString('base64').replace(/\+/g, '-').replace(/\//g, '_');

/** An HS256 JWT for a PostgREST role. The anon and service keys are not
 *  passwords; they are how the API roles are recognised, so they are derived
 *  from this instance's JWT secret rather than generated independently. */
function signJwt(role, secret) {
    const iat = Math.floor(Date.now() / 1000);
    const header = b64url(Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })));
    const payload = b64url(
        Buffer.from(JSON.stringify({ role, iss: 'supabase', iat, exp: iat + 315360000 })),
    );
    const signature = b64url(createHmac('sha256', secret).update(`${header}.${payload}`).digest());
    return `${header}.${payload}.${signature}`;
}

function readEnv() {
    const path = join(DIR, '.env');
    if (!existsSync(path)) return {};
    const out = {};
    for (const line of readFileSync(path, 'utf8').split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) continue;
        const eq = trimmed.indexOf('=');
        if (eq > 0) out[trimmed.slice(0, eq)] = trimmed.slice(eq + 1);
    }
    return out;
}

/** Generate what is missing and keep what is there. Re-running must never
 *  rotate CREDENTIALS_ENCRYPTION_KEY: every stored integration credential is
 *  encrypted with it, and a new one silently orphans all of them. */
function ensureEnv() {
    const env = readEnv();
    const keep = (key, make) => {
        if (!env[key]) env[key] = make();
    };

    keep('POSTGRES_PASSWORD', () => token(40));
    keep('JWT_SECRET', () => token(64));
    keep('CREDENTIALS_ENCRYPTION_KEY', fernetKey);
    keep('WORKFLOW_JWT_SECRET', () => token(64));
    keep('CRON_SCHEDULER_SECRET', () => token(64));
    keep('SESSION_SECRET', () => token(64));
    keep('OBJECT_STORAGE_ACCESS_KEY_ID', () => `noclick-${token(12)}`);
    keep('OBJECT_STORAGE_SECRET_ACCESS_KEY', () => token(40));
    // Signed with JWT_SECRET, so these must be minted after it exists.
    keep('ANON_KEY', () => signJwt('anon', env.JWT_SECRET));
    keep('SERVICE_ROLE_KEY', () => signJwt('service_role', env.JWT_SECRET));

    keep('NOCLICK_APP_URL', () => process.env.NOCLICK_APP_URL || 'http://localhost:3000');
    keep('NOCLICK_API_URL', () => process.env.NOCLICK_API_URL || 'http://api.localhost:8000');
    keep('NOCLICK_RELAY_URL', () => process.env.NOCLICK_RELAY_URL || 'ws://api.localhost:8000/relay');
    keep('NOCLICK_SUPABASE_URL', () => process.env.NOCLICK_SUPABASE_URL || 'http://supabase.localhost:8001');
    keep('NOCLICK_STORAGE_URL', () => process.env.NOCLICK_STORAGE_URL || 'http://storage.localhost:9000');
    keep('NOCLICK_APP_PORT', () => '3000');
    keep('NOCLICK_API_PORT', () => '8000');
    keep('NOCLICK_SUPABASE_PORT', () => '8001');
    keep('NOCLICK_STORAGE_PORT', () => '9000');
    keep('NOCLICK_AUTOCONFIRM_EMAIL', () => 'true');
    keep('NOCLICK_DISABLE_SIGNUP', () => 'false');
    for (const optional of [
        'SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'FROM_EMAIL',
        'RESEND_API_KEY', 'INVITE_FROM_EMAIL', 'INBOUND_EMAIL_DOMAIN', 'EMAIL_RELAY_SECRET',
        'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'GEMINI_API_KEY', 'REDIS_URL',
        'POSTHOG_API_KEY', 'HONEYCOMB_API_KEY', 'OUTBOUND_ALLOW_PRIVATE_IPS',
        'HTTP_NODE_ALLOW_PRIVATE_IPS',
        'GEOIP_LOOKUP_URL', 'WAHOOKS_API_KEY',
    ]) {
        keep(optional, () => '');
    }

    writeFileSync(
        join(DIR, '.env'),
        [
            '# NoClick Community — instance configuration. Generated by `npx noclick`.',
            '#',
            '# SECRETS. Do not commit this file, and back up CREDENTIALS_ENCRYPTION_KEY',
            '# somewhere else: without it every stored integration credential is unreadable.',
            '',
            ...Object.entries(env).map(([k, v]) => `${k}=${v}`),
            '',
        ].join('\n'),
        { mode: 0o600 },
    );
    return env;
}

// ── Commands ─────────────────────────────────────────────────────────────────

async function waitFor(url, seconds = 300) {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
        try {
            await fetch(url, { signal: AbortSignal.timeout(3000) });
            return true;
        } catch {
            await new Promise((resolve) => setTimeout(resolve, 2000));
        }
    }
    return false;
}

async function start({ build = true } = {}) {
    ensureSource();
    const env = ensureEnv();
    say('Building and starting (the first build takes a few minutes)');
    if (compose(build ? ['up', '-d', '--build'] : ['up', '-d']).status !== 0) {
        die('Compose failed to start the stack.');
    }

    const appUrl = env.NOCLICK_APP_URL || 'http://localhost:3000';
    say('Waiting for the app to answer');
    if (!(await waitFor(appUrl))) {
        die(
            `The app did not answer at ${appUrl} within five minutes.\n` +
            '  The containers are still running; see what they say:\n' +
            '    npx noclick logs',
        );
    }
    console.log(`\n${green('✓')} NoClick is running at ${bold(appUrl)}\n`);
    console.log('  Create the first account there; sign-ups are confirmed without');
    console.log('  email until you configure SMTP.\n');
    console.log(dim(`  Source and configuration:  ${DIR}`));
    console.log(dim('  Logs:                      npx noclick logs'));
    console.log(dim('  Stop:                      npx noclick stop\n'));
    console.log(`  Back up ${join(DIR, '.env')} — ${bold('CREDENTIALS_ENCRYPTION_KEY')} is in it,`);
    console.log('  and without that key a restored database cannot read any credential.');
}

function requireInstalled() {
    if (!existsSync(join(DIR, 'docker-compose.yml'))) {
        die(`No NoClick install at ${DIR}. Run \`npx noclick\` first, or set NOCLICK_DIR.`);
    }
}

const HELP = `${bold('npx noclick')} — run a NoClick instance on this machine

  ${bold('noclick')}              install if needed, then start
  ${bold('noclick stop')}         stop the containers, keep the data
  ${bold('noclick restart')}      start again without rebuilding
  ${bold('noclick update')}       fetch the latest version and restart
  ${bold('noclick logs')} [svc]   follow the logs
  ${bold('noclick status')}       what is running
  ${bold('noclick where')}        print the install directory
  ${bold('noclick doctor')}       check this machine
  ${bold('noclick uninstall')}    remove the containers and all data

${dim('Environment: NOCLICK_DIR, NOCLICK_REF, NOCLICK_REPO, NOCLICK_APP_URL')}`;

async function main() {
    const [command = 'start', ...rest] = process.argv.slice(2);

    switch (command) {
        case 'start':
        case 'up':
            return start();

        case 'stop':
        case 'down':
            requireInstalled();
            compose(['stop']);
            return;

        case 'restart':
            requireInstalled();
            return start({ build: false });

        case 'update':
            requireInstalled();
            updateSource();
            return start();

        case 'logs':
            requireInstalled();
            compose(['logs', '--tail', '200', '-f', ...rest]);
            return;

        case 'status':
        case 'ps':
            requireInstalled();
            compose(['ps']);
            return;

        case 'where':
            console.log(DIR);
            return;

        case 'doctor': {
            const [cmd, base] = requireDocker();
            console.log(`${green('✓')} docker            ${capture('docker', ['--version'])}`);
            console.log(`${green('✓')} docker compose    ${capture(cmd, [...base, 'version'])}`);
            console.log(
                `${have('git') ? green('✓') : red('✗')} git               ` +
                `${capture('git', ['--version']) || 'not found'}`,
            );
            const installed = existsSync(join(DIR, 'docker-compose.yml'));
            console.log(
                `${installed ? green('✓') : dim('·')} install           ` +
                `${installed ? DIR : `nothing at ${DIR} yet`}`,
            );
            if (installed) {
                const env = readEnv();
                for (const key of ['NOCLICK_APP_URL', 'NOCLICK_API_URL']) {
                    console.log(`${dim('·')} ${key.padEnd(17)} ${env[key] || dim('unset')}`);
                }
            }
            return;
        }

        case 'uninstall': {
            requireInstalled();
            const rl = createInterface({ input: process.stdin, output: process.stdout });
            const answer = await rl.question(
                red('This deletes the database and every uploaded file. Type "delete" to confirm: '),
            );
            rl.close();
            if (answer.trim() !== 'delete') {
                console.log('Left alone.');
                return;
            }
            compose(['down', '-v']);
            console.log(`Containers and data removed. ${DIR} is still there — delete it yourself.`);
            return;
        }

        case 'help':
        case '--help':
        case '-h':
            console.log(HELP);
            return;

        default:
            die(`Unknown command "${command}". Try \`npx noclick help\`.`);
    }
}

main().catch((err) => die(err?.stack || String(err)));
