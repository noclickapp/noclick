// Starts the app's server build as a Worker (../wrangler.jsonc) on the Workers runtime, locally, and asks it for the
// sign-in page. The runtime refuses a Worker that does I/O, sets a timer or makes a random value while its modules
// load (Cloudflare error 10021), which Node allows, so only this catches a module-scope `crypto.randomUUID()`.
// Run it after `pnpm build` in app/ (scripts/check.sh does). It fetches wrangler with npx, at the version below, whose
// runtime must support wrangler.jsonc's compatibility_date: moving that date past it fails here until this moves too.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const WRANGLER = 'wrangler@4.160.1';
const START_S = 180;

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// The deploy config as it stands, but for its build command (the app is built already) and with absolute paths, so
// the copy can live outside the repository. Its comments are whole lines.
const config = JSON.parse(
    readFileSync(join(root, 'wrangler.jsonc'), 'utf8')
        .split('\n')
        .filter((line) => !line.trim().startsWith('//'))
        .join('\n'),
);
delete config.build;
config.main = join(root, config.main);
config.assets = { ...config.assets, directory: join(root, config.assets.directory) };
config.observability = { enabled: false };

const freePort = () =>
    new Promise((done, fail) => {
        const server = createServer().listen(0, '127.0.0.1', () => {
            const { port } = server.address();
            server.close(() => done(port));
        });
        server.on('error', fail);
    });

const work = mkdtempSync(join(tmpdir(), 'noclick-worker-'));
const configPath = join(work, 'wrangler.json');
writeFileSync(configPath, JSON.stringify(config));
const port = await freePort();
const inspector = await freePort();

const settings = {
    NOCLICK_API_KEY: 'check',
    APP_PASSWORD: 'check-check-check',
    SESSION_SECRET: 'c'.repeat(64),
};
const args = ['--yes', WRANGLER, 'dev', '-c', configPath, '--ip', '127.0.0.1', '--port', String(port),
    '--inspector-port', String(inspector), '--show-interactive-dev-session=false', '--persist-to', join(work, 'state')];
for (const [name, value] of Object.entries(settings)) args.push('--var', `${name}:${value}`);

const wrangler = spawn('npx', args, {
    cwd: work,
    env: { ...process.env, CI: '1', WRANGLER_SEND_METRICS: 'false' },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: true,
});
let output = '';
const ready = new Promise((done, fail) => {
    const read = (chunk) => {
        output += chunk;
        if (/Ready on /.test(output)) done();
    };
    wrangler.stdout.on('data', read);
    wrangler.stderr.on('data', read);
    wrangler.on('exit', (code) => fail(new Error(`wrangler dev exited (${code}) before the Worker started`)));
    setTimeout(() => fail(new Error(`the Worker didn't start in ${START_S}s`)), START_S * 1000).unref();
});

let failure = null;
try {
    await ready;
    const response = await fetch(`http://127.0.0.1:${port}/login`, { redirect: 'manual' });
    if (response.status !== 200) failure = new Error(`GET /login answered ${response.status}, not 200`);
} catch (error) {
    failure = error;
} finally {
    try {
        process.kill(-wrangler.pid, 'SIGTERM');
    } catch {
        // Gone already.
    }
    rmSync(work, { recursive: true, force: true });
}

if (failure) {
    process.stderr.write(`${output}\n`);
    console.error(`The app doesn't start as a Worker: ${failure.message}`);
    process.exit(1);
}
console.log('The app starts as a Worker and serves /login.');
