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
let retry = false;
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
  retry = false;
  socket = new WebSocket(address);
  socket.addEventListener('message', ({data}) => {
    const frame = JSON.parse(data);
    if (frame.event === 'connect.challenge') {
      socket.send(JSON.stringify({type:'req', id:'connect', method:'connect', params:{
        minProtocol:4, maxProtocol:4,
        client:{id:'gateway-client', version:'1.0.0', platform:process.platform, mode:'backend'},
        role:'operator', scopes:['operator.read','operator.write','operator.admin'], caps:[], auth:{token},
      }}));
    } else if (frame.type === 'res' && frame.id === 'connect') {
      if (frame.ok) {
        ready = true;
        emit({method:'bridge/ready', params:{}});
      } else if (frame.error?.details?.reason === 'startup-sidecars' && Date.now() < deadline) {
        retry = true;
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
  socket.addEventListener('error', () => {
    if (!ready && Date.now() < deadline) retry = true;
    else stop(1);
  });
  socket.addEventListener('close', () => {
    if (retry && !ready && !stopping) setTimeout(connect, 200);
    else if (!stopping) stop(1); // Never replay inputs after a connection loss.
  });
}
createInterface({input:process.stdin}).on('line', line => {
  if (!ready) return stop(1);
  const request = JSON.parse(line);
  const id = String(request.id);
  requestIds.set(id, request.id);
  socket.send(JSON.stringify({type:'req', id, method:request.method, params:request.params || {}}));
}).on('close', () => stop());
connect();
