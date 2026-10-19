// Exercise startup failures whose error event is not followed by close (Node 22),
// both events (Node 24), and an explicit not-yet-ready gateway handshake.
// Scenario 'gateway': refused until the fake gateway process says it is up.
// Scenario 'silent': accepted, then never a frame, an error or a close.
import { existsSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

// NOCLICK_TEST_CLOCK_SCALE runs the bridge's deadlines (Date.now) that many
// times faster than real time, so a 60s start window elapses in moments.
const scale = Number(process.env.NOCLICK_TEST_CLOCK_SCALE || 1);
const realNow = Date.now.bind(Date);
const t0 = realNow();
Date.now = () => t0 + (realNow() - t0) * scale;

let attempts = 0;
const scenario = process.env.NOCLICK_WS_SCENARIO;
globalThis.WebSocket = class extends EventTarget {
  constructor() {
    super();
    this.attempt = ++attempts;
    queueMicrotask(() => {
      if (scenario === 'silent') return;
      if (scenario === 'gateway' && !existsSync(process.env.NOCLICK_TEST_GATEWAY_UP)) {
        this.dispatchEvent(new Event('error'));
      } else if (this.attempt === 1 && scenario.startsWith('error')) {
        this.dispatchEvent(new Event('error'));
        if (scenario === 'error-close') this.dispatchEvent(new Event('close'));
      } else this.message({event: 'connect.challenge'});
    });
  }
  message(frame) {
    this.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(frame)}));
  }
  send(line) {
    const request = JSON.parse(line);
    queueMicrotask(() => {
      if (request.method === 'connect') {
        const pending = this.attempt === 1 && scenario === 'sidecars';
        this.message({type: 'res', id: request.id, ok: !pending,
          error: pending ? {details: {reason: 'startup-sidecars'}} : undefined});
      } else if (request.method === 'probe') {
        this.message({type: 'res', id: request.id, ok: true, payload: {attempts}});
      } else if (request.method === 'disconnect') {
        // A failure after hello-ok must terminate, never reconnect or replay.
        this.dispatchEvent(new Event('error'));
      }
    });
  }
  close() {} // No close event: startup retry must not depend on one.
};

await import(pathToFileURL(process.argv[2]).href);
