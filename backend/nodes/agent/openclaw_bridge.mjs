// Own one local OpenClaw gateway and translate its public WS frames to JSONL.
// Node's built-in WebSocket avoids an additional transport dependency.
import { spawn } from 'node:child_process';
import { readdirSync, rmSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { createInterface } from 'node:readline';

const command = JSON.parse(process.env.NOCLICK_OPENCLAW_COMMAND);
const address = process.env.NOCLICK_OPENCLAW_URL;
const token = process.env.OPENCLAW_GATEWAY_TOKEN;
const configPath = process.env.OPENCLAW_CONFIG_PATH;
// Each gateway start's window to accept a connection, and one repair's own
// bound (nodes/agent/openclaw_protocol.py owns both).
const startMs = Number(process.env.NOCLICK_OPENCLAW_START_MS);
const doctorMs = Number(process.env.NOCLICK_OPENCLAW_DOCTOR_MS);
if (!(startMs > 0 && doctorMs > 0 && configPath)) {
  process.stderr.write('NOCLICK_OPENCLAW_START_MS, NOCLICK_OPENCLAW_DOCTOR_MS and OPENCLAW_CONFIG_PATH are required\n');
  process.exit(2);
}
// NoClick writes the whole config before every start, so OpenClaw's copies of
// an earlier one (its .bak ring, last-good) hold replaced settings and tokens.
// A gateway restores .bak over a config that looks clobbered to it (no `meta`,
// or under half the size of the last one it ran), and doctor restores last-good.
const configName = basename(configPath);
for (const name of readdirSync(dirname(configPath))) {
  if (name.startsWith(`${configName}.bak`) || name === `${configName}.last-good`) {
    rmSync(join(dirname(configPath), name), {force: true});
  }
}
// A gateway registers a 30-minute heartbeat, a weekly skill review and a daily
// agent turn as it starts. NoClick schedules agent work itself and stops a
// gateway soon after its turn, so no OpenClaw automation runs in one it owns.
const env = {...process.env, OPENCLAW_SKIP_CRON: '1'};
let child;
let migrationRestarted = false;
let repaired = false;
let repairing = false;
let socket;
let ready = false;
let stopping = false;
let deadline = Date.now() + startMs;
const startTimedOut = () => !repairing && Date.now() >= deadline;
const requestIds = new Map();
const emit = value => process.stdout.write(JSON.stringify(value) + '\n');

function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  socket?.close();
  child.kill('SIGTERM');
  const timer = setTimeout(() => { child.kill('SIGKILL'); process.exit(code); }, 2000);
  child.once('exit', () => { clearTimeout(timer); process.exit(code); });
  if (child.exitCode !== null) process.exit(code);
}
function run(args, onExit) {
  let diagnostics = '';
  child = spawn(command[0], args, {stdio:['ignore','pipe','pipe'], env});
  child.stdout.pipe(process.stderr);
  child.stderr.pipe(process.stderr);
  child.stderr.on('data', data => { diagnostics = (diagnostics + data).slice(-4096); });
  child.on('error', error => { process.stderr.write(error.message + '\n'); stop(1); });
  child.on('exit', code => { if (!stopping) onExit(code, diagnostics); });
}
function launch() {
  run(command.slice(1), (code, diagnostics) => {
    // Upstream explicitly requests one restart after installing a configured
    // plugin. This is before hello-ok or any user input; never restart a run.
    if (!ready && !migrationRestarted && diagnostics.includes('plugin migration inputs changed during startup convergence')) {
      migrationRestarted = true;
      launch();
    // State an older OpenClaw wrote (a conversation kept across a version bump)
    // that startup will not migrate itself: upstream's procedure is one
    // `doctor --fix` against the same state, then start again.
    } else if (!ready && !repaired && diagnostics.includes('openclaw doctor --fix')) {
      repaired = repairing = true;
      const timer = setTimeout(() => {
        process.stderr.write(`openclaw doctor --fix did not finish within ${doctorMs / 1000}s\n`);
        stop(1);
      }, doctorMs);
      run(['doctor', '--fix', '--non-interactive'], code => {
        clearTimeout(timer);
        repairing = false;
        if (code !== 0) return stop(code || 1);
        deadline = Date.now() + startMs;
        launch();
      });
    } else stop(code || 1);
  });
}
launch();
process.on('SIGTERM', () => stop());
process.on('SIGINT', () => stop());

function connect() {
  if (stopping) return;
  const ws = socket = new WebSocket(address);
  let retryScheduled = false;
  function retryStartup() {
    if (stopping || socket !== ws || retryScheduled) return;
    if (ready || startTimedOut()) return stop(1);
    // Node 22 can emit error without close after a refused connection. Retry
    // from either event, once per socket, and only before accepting any input.
    retryScheduled = true;
    ws.close();
    setTimeout(() => { if (!ready && socket === ws) connect(); }, 200);
  }
  ws.addEventListener('message', ({data}) => {
    if (stopping || socket !== ws || retryScheduled) return;
    const frame = JSON.parse(data);
    if (frame.event === 'connect.challenge') {
      ws.send(JSON.stringify({type:'req', id:'connect', method:'connect', params:{
        minProtocol:4, maxProtocol:4,
        client:{id:'gateway-client', version:'1.0.0', platform:process.platform, mode:'backend'},
        role:'operator', scopes:['operator.read','operator.write','operator.admin'], caps:[], auth:{token},
      }}));
    } else if (frame.type === 'res' && frame.id === 'connect') {
      if (frame.ok) {
        ready = true;
        emit({method:'bridge/ready', params:{}});
      } else if (frame.error?.details?.reason === 'startup-sidecars' && !startTimedOut()) {
        retryStartup();
      } else {
        process.stderr.write((frame.error?.message || 'OpenClaw connection rejected') + '\n');
        stop(1);
      }
    } else if (frame.type === 'res') {
      const id = requestIds.get(frame.id);
      requestIds.delete(frame.id);
      emit(frame.ok ? {id, result:frame.payload} : {id, error:frame.error});
    } else if (frame.type === 'event') {
      emit({method:frame.event, params:frame.payload || {}});
    }
  });
  ws.addEventListener('error', retryStartup);
  ws.addEventListener('close', retryStartup); // Never reconnect after hello-ok.
}
createInterface({input:process.stdin}).on('line', line => {
  if (!ready) return stop(1);
  const request = JSON.parse(line);
  const id = String(request.id);
  requestIds.set(id, request.id);
  socket.send(JSON.stringify({type:'req', id, method:request.method, params:request.params || {}}));
}).on('close', () => stop());
connect();
// A gateway that accepts the connection and never answers raises no error or
// close to retry on, so the start window is also held by the clock.
const watchdog = setInterval(() => {
  if (ready || stopping) return clearInterval(watchdog);
  if (startTimedOut()) {
    process.stderr.write(`OpenClaw gateway did not answer within ${startMs / 1000}s\n`);
    stop(1);
  }
}, 250);
