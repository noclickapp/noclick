// Watch: a token from POST /v1/watch/tokens, then a socket that says which objects changed. The socket offers only the
// protocol's name and sends the token as its first frame (never a header or the URL), a reconnect resumes after the
// last change (the URL's `after`), and only what retrying can't fix ends it.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const TOKEN = (n: number) => ({
  object: "watch_token", url: `wss://api.test/v1/watch/socket/r_${n}?ticket=tk_${n}`, token: `tok_${n}`,
  expires_at: "2026-11-18T10:01:00Z", connection_ends_at: "2026-11-18T10:15:00Z", objects: ["deployment", "channel"],
  user_id: null,
});

class FakeSocket {
  static opened: FakeSocket[] = [];
  readonly sent: string[] = [];
  onopen?: () => void;
  onmessage?: (event: { data: unknown }) => void;
  onclose?: (event: { code: number; reason: string }) => void;
  onerror?: () => void;
  closedWith?: number;
  readonly url: string;
  readonly protocols: string[];

  constructor(url: string, protocols: string[] = []) {
    this.url = url;
    this.protocols = protocols;
    FakeSocket.opened.push(this);
    queueMicrotask(() => this.onopen?.());
  }
  send(data: string) {
    this.sent.push(data);
  }
  close(code: number) {
    this.closedWith = code;
  }
  receive(message: unknown) {
    this.onmessage?.({ data: typeof message === "string" ? message : JSON.stringify(message) });
  }
  end(code: number, reason = "") {
    this.onclose?.({ code, reason });
  }
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const auth = (token: string) => JSON.stringify({ type: "auth", token });

/** Every wait `watch` makes takes no time; the list is how long each would have been. */
function noWaits(t: { mock: { method: (...args: never[]) => unknown } }): number[] {
  const realSetTimeout = globalThis.setTimeout;
  const waits: number[] = [];
  (t.mock.method as (o: object, m: string, f: unknown) => unknown)(globalThis, "setTimeout",
    ((fn: () => void, ms?: number) => {
      waits.push(ms ?? 0);
      return realSetTimeout(fn, 0);
    }) as typeof setTimeout);
  return waits;
}

async function opened(n: number): Promise<FakeSocket> {
  for (let i = 0; i < 100 && FakeSocket.opened.length < n; i++) await tick();
  const socket = FakeSocket.opened[n - 1];
  assert.ok(socket, `socket ${n} opened`);
  await tick();
  return socket;
}

test("watchToken asks for the objects, the page's origin and the user, and reads the answer", async () => {
  const { api } = setup();
  const minted = api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }));
  const token = await nc.watchToken({ objects: ["deployment"], origin: "https://app.example", user: "user_42" });
  assert.deepEqual(minted.last.body, { objects: ["deployment"], origin: "https://app.example" });
  assert.equal(minted.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual([token.url, token.token, token.objects], ["wss://api.test/v1/watch/socket/r_1?ticket=tk_1", "tok_1", ["deployment", "channel"]]);
  assert.equal(token.connectionEndsAt?.toISOString(), "2026-11-18T10:15:00.000Z");
});

test("watch authenticates first, yields ready and changes, ignores unknown types, and resumes after a renew", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  const minted = api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }), json(TOKEN(2), { status: 201 }));
  const controller = new AbortController();
  const statuses: string[] = [];
  const seen: nc.WatchMessage[] = [];
  const done = (async () => {
    for await (const message of nc.watch({
      WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal, objects: ["deployment"],
      onStatus: (s) => statuses.push(s),
    })) seen.push(message);
  })();

  const first = await opened(1);
  assert.equal(first.url, "wss://api.test/v1/watch/socket/r_1?ticket=tk_1", "the url as minted, its ticket and all");
  assert.deepEqual(first.protocols, ["noclick.watch"], "only the protocol's name rides the header");
  assert.deepEqual(first.sent, [auth("tok_1")], "the token is the first frame, sent as the socket opens");
  assert.deepEqual(minted.last.body, { objects: ["deployment"] });
  first.receive({ type: "ready", resumed: false });
  first.receive({ type: "change", id: "c_1", at: "2026-11-18T10:00:00Z", object: "deployment", object_id: "d1",
                  status: "ready", parent: { object: "project", id: "p1" } });
  first.receive({ type: "something_new", x: 1 });
  first.receive({ type: "typing", channel_id: "ch1", user_id: "account", typing: true });
  first.end(4000, "lifetime");

  const second = await opened(2);
  assert.equal(second.url, "wss://api.test/v1/watch/socket/r_2?ticket=tk_2&after=c_1");
  assert.deepEqual(second.protocols, ["noclick.watch"]);
  assert.deepEqual(second.sent, [auth("tok_2")], "each socket sends its own fresh token first");
  second.receive({ type: "ready", resumed: true });
  second.receive({ type: "reset" });
  await tick();
  controller.abort();
  await done;

  assert.deepEqual(seen.map((m) => m.type), ["ready", "change", "typing", "ready", "reset"]);
  const change = seen[1] as nc.WatchChange;
  assert.deepEqual([change.object, change.objectId, change.status, change.parent], ["deployment", "d1", "ready", { object: "project", id: "p1" }]);
  assert.equal((seen[3] as nc.WatchReady).resumed, true);
  assert.equal(second.closedWith, 1000, "aborting closes the socket");
  assert.deepEqual(statuses, ["connecting", "live", "reconnecting", "live", "stopped"]);
});

test("a refused socket gets one fresh token, after waiting out a revoke's margin; refused again, watch throws", async (t) => {
  FakeSocket.opened = [];
  const waits = noWaits(t);
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }), json(TOKEN(2), { status: 201 }),
    json(TOKEN(3), { status: 201 }));
  const run = (async () => {
    for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket })) { /* reading */ }
  })();
  const first = await opened(1);
  first.receive({ type: "ready", resumed: false });
  first.end(4401, "Access was revoked");
  const second = await opened(2);
  second.end(4401, "That token was used already");
  await assert.rejects(run, (err: unknown) => err instanceof nc.WatchRefused && /used already/.test(String(err)));
  assert.ok(waits.some((ms) => ms >= 8_000 && ms <= 12_000), `waited ${JSON.stringify(waits.filter((ms) => ms > 0))}`);
});

test("a token call refused for good ends watch with its error; a custom token source is used instead of the client", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", apiError(409, "not_available", "Watching for changes isn't available"));
  await assert.rejects(async () => {
    for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket })) { /* reading */ }
  }, nc.NotAvailable);

  const asked: string[] = [];
  const controller = new AbortController();
  const run = (async () => {
    for await (const _ of nc.watch({
      WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal,
      token: async () => { asked.push("mine"); return { url: "wss://relay.test/v1/watch/socket/r_9", token: "tok_mine" }; },
    })) { /* reading */ }
  })();
  const socket = await opened(1);
  assert.equal(socket.url, "wss://relay.test/v1/watch/socket/r_9");
  assert.deepEqual(asked, ["mine"]);
  controller.abort();
  await run;
});

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test("a reader slower than the room is handed one reset in place of what queued up past its bound", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }));
  const controller = new AbortController();
  const iterator = nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })[Symbol.asyncIterator]();
  const first = iterator.next();
  const socket = await opened(1);
  socket.receive({ type: "ready", resumed: false });
  assert.equal(((await first).value as nc.WatchMessage).type, "ready");
  const FLOOD = 20_000; // under 7 minutes of a room's ceiling for one viewer
  for (let i = 0; i < FLOOD; i++) {
    socket.receive({ type: "change", id: `c_${i}`, at: "2026-11-18T10:00:00Z", object: "channel", object_id: "ch1", change: "message" });
  }
  socket.receive({ type: "change", id: "c_last", at: "2026-11-18T10:00:00Z", object: "channel", object_id: "last" });
  const seen: nc.WatchMessage[] = [];
  const drained = (async () => {
    for (;;) {
      const { value, done } = await iterator.next();
      if (done) return;
      seen.push(value as nc.WatchMessage);
      if ((value as nc.WatchChange).objectId === "last") controller.abort();
    }
  })();
  await drained;
  const changes = seen.filter((m) => m.type === "change").length;
  assert.equal(seen[0].type, "reset", "what queued past its bound gave way to a reset, first");
  assert.equal(seen.filter((m) => m.type === "reset").length, 1);
  assert.ok(changes < 1_001, `the reader was handed ${changes} of ${FLOOD} queued changes`);
  assert.equal((seen.at(-1) as nc.WatchChange).objectId, "last", "what came after the reset still arrives");
});

test("watchers whose sockets drop together come back spread out", async () => {
  FakeSocket.opened = [];
  const openedAt: number[] = [];
  class Timed extends FakeSocket {
    constructor(url: string) {
      super(url);
      openedAt.push(Date.now());
    }
  }
  const { api } = setup();
  const WATCHERS = 12;
  api.on("POST", "/v1/watch/tokens", ...Array.from({ length: WATCHERS * 2 }, (_, i) => json(TOKEN(i + 1), { status: 201 })));
  const controller = new AbortController();
  const runs = Array.from({ length: WATCHERS }, () => (async () => {
    for await (const _ of nc.watch({ WebSocket: Timed as unknown as typeof WebSocket, signal: controller.signal })) { /* reading */ }
  })());
  await opened(WATCHERS);
  const first = FakeSocket.opened.slice(0, WATCHERS);
  for (const socket of first) socket.receive({ type: "ready", resumed: false });
  await tick();
  const dropped = Date.now();
  for (const socket of first) socket.end(1006, ""); // the room went away under all of them
  for (let i = 0; i < 400 && FakeSocket.opened.length < WATCHERS * 2; i++) await sleep(5);
  const back = openedAt.slice(WATCHERS).map((at) => at - dropped);
  controller.abort();
  await Promise.all(runs);
  assert.equal(back.length, WATCHERS);
  const spread = Math.max(...back) - Math.min(...back);
  assert.ok(spread >= 100, `${WATCHERS} watchers came back ${Math.min(...back)}-${Math.max(...back)} ms after the drop`);
});

for (const url of ["ws://relay.example/v1/watch/socket/r_1", "http://relay.example/x", "not a url"]) {
  test(`a token is never sent to ${url}`, async () => {
    FakeSocket.opened = [];
    const { api } = setup();
    api.on("POST", "/v1/watch/tokens", json({ ...TOKEN(1), url }, { status: 201 }));
    await assert.rejects(async () => {
      for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket })) { /* reading */ }
    }, (err: unknown) => err instanceof nc.NoClickError && /wss:\/\//.test(String(err)));
    assert.deepEqual(FakeSocket.opened, [], "no socket was opened for it");
  });
}

test("on this machine a plain ws:// socket will do", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", json({ ...TOKEN(1), url: "ws://localhost:8787/v1/watch/socket/r_1" }, { status: 201 }));
  const controller = new AbortController();
  const run = (async () => {
    for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) { /* reading */ }
  })();
  const socket = await opened(1);
  assert.deepEqual(socket.protocols, ["noclick.watch"]);
  assert.deepEqual(socket.sent, [auth("tok_1")]);
  controller.abort();
  await run;
});

test("frames that are not JSON objects, or carry wrong types, never reach the reader or throw", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }));
  const controller = new AbortController();
  const seen: nc.WatchMessage[] = [];
  const run = (async () => {
    for await (const message of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) seen.push(message);
  })();
  const socket = await opened(1);
  socket.receive({ type: "ready", resumed: false });
  for (const frame of ["[]", "null", "42", '"text"', "{", "", { type: ["change"] }, { type: "change", id: 5, object: null, parent: "x", at: 12 },
    { type: "typing" }, { type: "ready", resumed: "yes" }, { __proto__: { type: "change" } }]) socket.receive(frame);
  socket.receive({ type: "reset" });
  await tick();
  controller.abort();
  await run;
  assert.equal(seen[0].type, "ready");
  assert.equal(seen.at(-1)?.type, "reset");
  for (const message of seen) assert.ok(["ready", "change", "typing", "reset"].includes(message.type));
});

test("the token is the socket's first frame, never its protocol or URL, and a browser's origin goes with the token call", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  const minted = api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }));
  (globalThis as { location?: unknown }).location = { origin: "https://app.example" };
  try {
    const controller = new AbortController();
    const run = (async () => {
      for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) { /* reading */ }
    })();
    const socket = await opened(1);
    assert.ok(!socket.url.includes("tok_1"));
    assert.deepEqual(socket.protocols, ["noclick.watch"]);
    assert.deepEqual(socket.sent, [auth("tok_1")]);
    assert.deepEqual(minted.last.body, { origin: "https://app.example" });
    controller.abort();
    await run;
  } finally {
    delete (globalThis as { location?: unknown }).location;
  }
});

test("a room that refuses twice ends the watch instead of looping on fresh tokens", async (t) => {
  FakeSocket.opened = [];
  noWaits(t);
  const { api } = setup();
  const minted = api.on("POST", "/v1/watch/tokens", ...Array.from({ length: 6 }, (_, i) => json(TOKEN(i + 1), { status: 201 })));
  const run = (async () => {
    for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket })) { /* reading */ }
  })();
  (await opened(1)).end(4401, "revoked");
  (await opened(2)).end(4401, "revoked");
  await assert.rejects(run, (err: unknown) => err instanceof nc.WatchRefused);
  assert.equal(minted.calls.length, 2);
});

test("a socket that goes silent is dropped and reconnects", async (t) => {
  t.mock.timers.enable({ apis: ["setInterval", "Date"] });
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }), json(TOKEN(2), { status: 201 }));
  const controller = new AbortController();
  const run = (async () => {
    for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) { /* reading */ }
  })();
  const socket = await opened(1);
  socket.receive({ type: "ready", resumed: false });
  t.mock.timers.tick(30_000);
  assert.equal(socket.sent.at(-1), "ping", "it asks every 30 s");
  socket.receive("pong");
  t.mock.timers.tick(60_000);
  assert.equal(socket.closedWith, undefined, "it answered within a minute");
  t.mock.timers.tick(30_000);
  assert.equal(socket.closedWith, 4000, "nothing heard for over a minute: closed");
  controller.abort();
  await run;
});

test("a socket closed for its first frame (4400) or its silence (4408) backs off and sends a fresh token, never giving up", async (t) => {
  FakeSocket.opened = [];
  t.mock.method(Math, "random", () => 0.5);
  const waits = noWaits(t);
  const { api } = setup();
  const minted = api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }), json(TOKEN(2), { status: 201 }),
    json(TOKEN(3), { status: 201 }), json(TOKEN(4), { status: 201 }));
  const controller = new AbortController();
  const seen: nc.WatchMessage[] = [];
  const run = (async () => {
    for await (const message of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) seen.push(message);
  })();
  (await opened(1)).end(4408, 'No {"type": "auth"} frame within 30 s of connecting');
  (await opened(2)).end(4400, 'The first frame must be {"type": "auth", "token": "<token>"}');
  (await opened(3)).end(4408, "late again");
  const fourth = await opened(4);
  fourth.receive({ type: "ready", resumed: false });
  await tick();
  controller.abort();
  await run;
  assert.deepEqual(FakeSocket.opened.map((s) => s.sent[0]), [auth("tok_1"), auth("tok_2"), auth("tok_3"), auth("tok_4")]);
  assert.equal(minted.calls.length, 4, "a new token for each socket");
  // The token calls' own 60 s timeouts aside: the backoff climbs, as for any drop.
  assert.deepEqual(waits.filter((ms) => ms > 0 && ms < 60_000), [500, 1_000, 2_000]);
  assert.deepEqual(seen.map((m) => m.type), ["ready"]);
});

test("a room turned away waits half a minute, spread, before trying again", async (t) => {
  const realSetTimeout = globalThis.setTimeout;
  for (const [random, wait] of [[0, 15_000], [0.5, 30_000]] as const) {
    FakeSocket.opened = [];
    const waits: number[] = [];
    t.mock.method(Math, "random", () => random);
    t.mock.method(globalThis, "setTimeout", ((fn: () => void, ms?: number) => {
      waits.push(ms ?? 0);
      return realSetTimeout(fn, 0);
    }) as typeof setTimeout);
    const { api } = setup();
    api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }), json(TOKEN(2), { status: 201 }));
    const controller = new AbortController();
    const run = (async () => {
      for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) { /* reading */ }
    })();
    (await opened(1)).end(4429, "Too many connections");
    await opened(2);
    controller.abort();
    await run;
    t.mock.restoreAll();
    assert.ok(waits.includes(wait), `waited ${JSON.stringify(waits.filter((w) => w > 0))}, not ${wait}`);
  }
});

async function firstOutcome(url: string): Promise<{ opened: FakeSocket[]; error: unknown }> {
  FakeSocket.opened = [];
  const controller = new AbortController();
  let error: unknown = null;
  const run = (async () => {
    try {
      for await (const _ of nc.watch({
        WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal,
        token: async () => ({ url, token: "tok_secret" }),
      })) break;
    } catch (err) {
      error = err;
    }
  })();
  for (let i = 0; i < 20 && !FakeSocket.opened.length && !error; i++) await tick();
  controller.abort();
  await run;
  return { opened: [...FakeSocket.opened], error };
}

for (const url of ["wss://api.noclick.com/v1/watch/socket/r_1", "ws://localhost:8787/x", "ws://LOCALHOST/x",
                   "ws://127.0.0.1/x", "ws://[::1]:9/x", "ws://user:pw@localhost/x"]) {
  test(`a token goes to ${url}`, async () => {
    const { opened: sockets, error } = await firstOutcome(url);
    assert.equal(error, null);
    assert.equal(sockets.length, 1);
    assert.deepEqual(sockets[0].protocols, ["noclick.watch"]);
    assert.deepEqual(sockets[0].sent, [auth("tok_secret")]);
  });
}

for (const url of ["ws://api.noclick.com/x", "ws://localhost.evil.com/x", "ws://localhost@evil.com/x",
                   "ws://evil.com#@localhost", "ws://127.0.0.1.nip.io/x", "https://api.noclick.com/x", "not a url",
                   "ws://localhost./x"]) {
  test(`no token goes to ${url}`, async () => {
    const { opened: sockets, error } = await firstOutcome(url);
    assert.deepEqual(sockets, []);
    assert.ok(error instanceof nc.NoClickError, String(error));
    assert.ok(!String((error as Error).message).includes("tok_secret"));
    assert.ok(!JSON.stringify(error).includes("tok_secret"));
  });
}

test("a reader behind by more than the queue gets one reset, then everything after it", async () => {
  FakeSocket.opened = [];
  const controller = new AbortController();
  const iterator = nc.watch({
    WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal,
    token: async () => ({ url: "wss://api.test/x", token: "tok" }),
  })[Symbol.asyncIterator]();
  const first = iterator.next();
  const socket = await opened(1);
  socket.receive({ type: "ready", resumed: false });
  assert.equal(((await first).value as nc.WatchMessage).type, "ready");
  for (let i = 0; i < 1_500; i++) socket.receive({ type: "change", id: `c_${i}`, object: "domain", object_id: `d${i}` });
  const seen: nc.WatchMessage[] = [];
  for (let i = 0; i < 501; i++) seen.push((await iterator.next()).value as nc.WatchMessage);
  assert.equal(seen[0].type, "reset");
  assert.equal((seen[seen.length - 1] as nc.WatchChange).objectId, "d1499", "the last change after the reset still arrives");
  controller.abort();
  await iterator.return(undefined);
});

test("a resume rides the URL; a URL with a query keeps it", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", json({ ...TOKEN(1), url: "wss://api.test/v1/watch/socket/r_1?x=1" }, { status: 201 }),
    json({ ...TOKEN(2), url: "wss://api.test/v1/watch/socket/r_1?x=1" }, { status: 201 }));
  const controller = new AbortController();
  const run = (async () => {
    for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) { /* reading */ }
  })();
  const first = await opened(1);
  assert.equal(first.url, "wss://api.test/v1/watch/socket/r_1?x=1");
  first.receive({ type: "ready", resumed: false });
  first.receive({ type: "change", id: "c_AbCdEfGh_7", at: "2026-11-18T10:00:00Z", object: "domain", object_id: "d1" });
  first.end(4000, "lifetime");
  const second = await opened(2);
  assert.equal(second.url, "wss://api.test/v1/watch/socket/r_1?x=1&after=c_AbCdEfGh_7");
  controller.abort();
  await run;
});

test("review3 FINDING: a connection that drops right after ready never backs off", async (t) => {
  // `ready` resets the backoff, so a socket that opens and drops at once is retried every 0.25 to 0.75 s forever,
  // minting a token each time: the backoff never climbs, however many times in a row it happens.
  FakeSocket.opened = [];
  const waits = noWaits(t);
  const { api } = setup();
  const flaps = 8;
  api.on("POST", "/v1/watch/tokens", ...Array.from({ length: flaps + 1 }, (_, n) => json(TOKEN(n), { status: 201 })));
  const controller = new AbortController();
  const done = (async () => {
    for await (const _message of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) {
      // read everything
    }
  })();
  for (let n = 1; n <= flaps; n++) {
    const socket = await opened(n);
    socket.receive({ type: "ready", resumed: false });
    socket.end(1006);
  }
  await opened(flaps + 1);
  controller.abort();
  await done;
  // The reconnect waits: spread over half to one and a half of a backoff step (the HTTP client's own timers, whole
  // numbers, are not).
  const backoffs = waits.filter((ms) => !Number.isInteger(ms));
  assert.equal(backoffs.length, flaps, `waits: ${waits}`);
  assert.ok(Math.max(...backoffs) >= 5_000,
    `${flaps} drops in a row, each retried within ${Math.max(...backoffs).toFixed(0)} ms: ${backoffs.map((w) => w.toFixed(0))}`);
});

test("a connection that stayed up starts the backoff again", async (t) => {
  // Four drops right after ready climb the backoff; a connection that then stays up 30 s and drops is tried again
  // at the first step.
  FakeSocket.opened = [];
  const waits = noWaits(t);
  let now = 1_000_000;
  t.mock.method(Date, "now", () => now);
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", ...Array.from({ length: 7 }, (_, n) => json(TOKEN(n), { status: 201 })));
  const controller = new AbortController();
  const done = (async () => {
    for await (const _message of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) {
      // read everything
    }
  })();
  for (let n = 1; n <= 5; n++) {
    const socket = await opened(n);
    socket.receive({ type: "ready", resumed: false });
    await new Promise((resolve) => setImmediate(resolve));
    now += n === 5 ? 42_000 : 1_000;
    socket.end(1006);
  }
  await opened(6);
  controller.abort();
  await done;
  const backoffs = waits.filter((ms) => !Number.isInteger(ms));
  assert.equal(backoffs.length, 5, `waits: ${waits}`);
  assert.ok(backoffs[3] >= 2_500, `the fourth drop in a row waits a later step: ${backoffs}`);
  assert.ok(backoffs[4] <= 750, `after a connection that stayed up, the first step again: ${backoffs}`);
});

test("a page coming back into view asks its socket at once, and replaces one that doesn't answer, resuming after its last change", async (t) => {
  FakeSocket.opened = [];
  const waits = noWaits(t);
  let now = 1_000_000;
  t.mock.method(Date, "now", () => now);
  const page = Object.assign(new EventTarget(), { visibilityState: "visible" });
  (globalThis as { document?: unknown }).document = page;
  t.after(() => delete (globalThis as { document?: unknown }).document);
  const { api } = setup();
  api.on("POST", "/v1/watch/tokens", json(TOKEN(1), { status: 201 }), json(TOKEN(2), { status: 201 }));
  const controller = new AbortController();
  t.after(() => controller.abort());
  const run = (async () => {
    for await (const _ of nc.watch({ WebSocket: FakeSocket as unknown as typeof WebSocket, signal: controller.signal })) { /* reading */ }
  })();
  const socket = await opened(1);
  socket.receive({ type: "ready", resumed: false });
  socket.receive({ type: "change", id: "c_7", object: "deployment", object_id: "dep_1" });
  await tick();

  // It answers in time: kept.
  now += 60_000;
  page.dispatchEvent(new Event("visibilitychange"));
  assert.equal(socket.sent.at(-1), "ping");
  now += 100;
  socket.receive("pong");
  await tick();
  assert.equal(socket.closedWith, undefined);
  assert.ok(waits.includes(3_000), "it gives the answer a few seconds");

  // The phone cut it while the page was hidden: no answer, so it's dropped at once and another opens after c_7.
  now += 60_000;
  page.dispatchEvent(new Event("visibilitychange"));
  await tick();
  assert.equal(socket.closedWith, 4000);
  const next = await opened(2);
  assert.match(next.url, /after=c_7/);
  controller.abort();
  await run;
});
