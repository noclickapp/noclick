// Watch: a token from POST /v1/watch/tokens, then a socket that says which objects changed. The token goes in the
// first message (never the URL), a reconnect resumes after the last change, and only what retrying can't fix ends it.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const TOKEN = (n: number) => ({
  object: "watch_token", url: `wss://api.test/v1/watch/socket/r_${n}`, token: `tok_${n}`,
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

  constructor(url: string) {
    this.url = url;
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
  assert.deepEqual([token.url, token.token, token.objects], ["wss://api.test/v1/watch/socket/r_1", "tok_1", ["deployment", "channel"]]);
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
  assert.equal(first.url, "wss://api.test/v1/watch/socket/r_1");
  assert.deepEqual(JSON.parse(first.sent[0]), { type: "auth", token: "tok_1", after: null });
  assert.deepEqual(minted.last.body, { objects: ["deployment"] });
  first.receive({ type: "ready", resumed: false });
  first.receive({ type: "change", id: "c_1", at: "2026-11-18T10:00:00Z", object: "deployment", object_id: "d1",
                  status: "ready", parent: { object: "project", id: "p1" } });
  first.receive({ type: "something_new", x: 1 });
  first.receive({ type: "typing", channel_id: "ch1", user_id: "account", typing: true });
  first.end(4000, "lifetime");

  const second = await opened(2);
  assert.deepEqual(JSON.parse(second.sent[0]), { type: "auth", token: "tok_2", after: "c_1" });
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

test("a refused socket gets one fresh token; refused again before it's ready, watch throws", async () => {
  FakeSocket.opened = [];
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
  assert.deepEqual(JSON.parse(socket.sent[0]).token, "tok_1");
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

test("the token rides the first frame, never the URL, and a browser's origin is sent with the token call", async () => {
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
    assert.deepEqual(JSON.parse(socket.sent[0]), { type: "auth", token: "tok_1", after: null });
    assert.deepEqual(minted.last.body, { origin: "https://app.example" });
    controller.abort();
    await run;
  } finally {
    delete (globalThis as { location?: unknown }).location;
  }
});

test("a room that refuses twice ends the watch instead of looping on fresh tokens", async () => {
  FakeSocket.opened = [];
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
