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
