// Own one local OpenClaw gateway and translate its public WS frames to JSONL.
// Node's built-in WebSocket avoids an additional transport dependency.
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';

const command = JSON.parse(process.env.NOCLICK_OPENCLAW_COMMAND);
const address = process.env.NOCLICK_OPENCLAW_URL;
const token = process.env.OPENCLAW_GATEWAY_TOKEN;
let child;
let migrationRestarted = false;
let socket;
let ready = false;
let stopping = false;
const deadline = Date.now() + 60_000;
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
function launch() {
  let diagnostics = '';
  child = spawn(command[0], command.slice(1), {stdio:['ignore','pipe','pipe'], env:process.env});
  child.stdout.pipe(process.stderr);
  child.stderr.pipe(process.stderr);
  child.stderr.on('data', data => { diagnostics = (diagnostics + data).slice(-4096); });
  child.on('error', error => { process.stderr.write(error.message + '\n'); stop(1); });
  child.on('exit', code => {
    if (stopping) return;
    // Upstream explicitly requests one restart after installing a configured
    // plugin. This is before hello-ok or any user input; never restart a run.
    if (!ready && !migrationRestarted && diagnostics.includes('plugin migration inputs changed during startup convergence')) {
      migrationRestarted = true;
      launch();
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
    if (ready || Date.now() >= deadline) return stop(1);
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
      } else if (frame.error?.details?.reason === 'startup-sidecars' && Date.now() < deadline) {
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
