// A browser's live view in a page: `liveView` asks for a single-use token (watching, or driving once it's taken over),
// and `view` speaks the socket: the token as its first message (never the URL), the page's size and its pictures,
// what a person does on a view that drives it, and opening again with a new token each time it needs to.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { TestContext } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const BROWSER = {
  object: "browser", id: "br_1", status: "running", agent_id: "ag_1", conversation: "owner", held: false,
  created_at: "2026-11-19T10:00:00Z",
};
const URL_ = "wss://api.test/v1/browsers/live_views/attach";
const VIEW = (n: number, extra: Record<string, unknown> = {}) => ({
  object: "browser_live_view", browser_id: "br_1", control: false, thumb: false, url: URL_, token: `tok_${n}`,
  token_expires_at: "2026-11-19T10:02:00Z", ...extra,
});

class FakeSocket {
  static OPEN = 1;
  static opened: FakeSocket[] = [];
  readonly sent: string[] = [];
  binaryType = "blob";
  readyState = 0;
  onopen?: () => void;
  onmessage?: (event: { data: unknown }) => void;
  onclose?: (event: { code: number; reason: string }) => void;
  closedWith?: number;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.opened.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close(code: number) {
    this.closedWith = code;
  }
  // The server's side.
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  show(width = 1280, height = 800) {
    this.onmessage?.({ data: JSON.stringify({ type: "viewport", width, height }) });
    this.onmessage?.({ data: new Uint8Array([0xff, 0xd8]).buffer });
  }
  end(code: number, reason = "") {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

const Socket = FakeSocket as unknown as typeof WebSocket;
const tick = () => new Promise((resolve) => setImmediate(resolve));

async function opened(n: number): Promise<FakeSocket> {
  for (let i = 0; i < 100 && FakeSocket.opened.length < n; i++) await tick();
  const socket = FakeSocket.opened[n - 1];
  assert.ok(socket, `socket ${n} opened`);
  return socket;
}

test("liveView asks for a watching view's token, or a driving one's", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  const watch = api.on("POST", "/v1/browsers/br_1/live_view", json(VIEW(1, { thumb: true })));
  const drive = api.on("POST", "/v1/browsers/br_1/live_control", json(VIEW(2, { control: true })));
  const browser = nc.Browser.fromId("br_1");

  const tile = await browser.liveView({ thumb: true });
  assert.deepEqual(watch.last.body, { thumb: true });
  assert.deepEqual([tile.browserId, tile.thumb, tile.control, tile.url, tile.token], ["br_1", true, false, URL_, "tok_1"]);
  assert.equal(tile.tokenExpiresAt?.toISOString(), "2026-11-19T10:02:00.000Z");
  assert.equal((await browser.liveView()).thumb, true);  // the route's answer, whatever was asked
  assert.deepEqual(watch.last.body, { thumb: false });

  const driving = await browser.liveView({ control: true });
  assert.equal(drive.count, 1);
  assert.equal(drive.last.body, null);
  assert.equal(driving.control, true);
  await assert.rejects(browser.liveView({ control: true, thumb: true }), /full size/);
});

test("a token opens its view once, sent as the first message and never in the URL", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/browsers/br_1/live_view", json(VIEW(1)));
  const view = await nc.Browser.fromId("br_1").liveView();
  const pictures: number[] = [];
  const connection = view.connect({ WebSocket: Socket, onPicture: (jpeg) => pictures.push(jpeg.length) });
  const socket = await opened(1);
  assert.equal(socket.url, URL_);
  assert.ok(!socket.url.includes("tok_1"));
  socket.open();
  assert.deepEqual(JSON.parse(socket.sent[0]), { type: "auth", token: "tok_1" });
  socket.show();
  assert.deepEqual(pictures, [2]);
  assert.throws(() => view.connect({ WebSocket: Socket }), /once/);
  socket.end(4000);
  await tick();
  assert.equal(FakeSocket.opened.length, 1, "a view from a token alone doesn't open again");
  assert.equal(connection.state, "ended");
});

test("view shows the page's size and pictures, and a watching view takes no input", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("GET", "/v1/browsers/br_1", json(BROWSER));
  api.on("POST", "/v1/browsers/br_1/live_view", json(VIEW(1)));
  const seen: unknown[] = [];
  const view = nc.Browser.fromId("br_1").view({
    WebSocket: Socket, onViewport: (v) => seen.push(v), onPicture: (jpeg) => seen.push(Array.from(jpeg)),
    onState: (state) => seen.push(state),
  });
  const socket = await opened(1);
  socket.open();
  socket.show(390, 844);
  assert.deepEqual(seen, [{ width: 390, height: 844 }, "live", [0xff, 0xd8]]);
  assert.equal(view.control, false);
  assert.throws(() => view.send({ type: "tap", x: 1, y: 1 }), /only watches/);
  assert.deepEqual(socket.sent.map((s) => JSON.parse(s).type), ["auth"]);
  view.close();
  assert.equal(socket.closedWith, 1000);
});

test("a view that drives sends a person's input only once its connection has shown the page", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  const drive = api.on("POST", "/v1/browsers/br_1/live_control", json(VIEW(1, { control: true })));
  const view = nc.Browser.fromId("br_1").view({ control: true, WebSocket: Socket });
  assert.equal(view.control, true);
  view.send({ type: "tap", x: 4, y: 5 });  // before any connection: dropped
  const socket = await opened(1);
  assert.equal(drive.count, 1);
  socket.open();
  view.send({ type: "text", text: "hello" });  // open, but the page not shown yet: dropped
  socket.show();
  view.send({ type: "key", key: "Enter" });
  view.send({ type: "mouse", action: "move", x: 6, y: 7 });
  assert.deepEqual(socket.sent.map((s) => JSON.parse(s)), [
    { type: "auth", token: "tok_1" }, { type: "key", key: "Enter" }, { type: "mouse", action: "move", x: 6, y: 7 },
  ]);
  view.close();
});

test("input reaches a view that opened again only once it has shown the page, never what came before", async (t) => {
  FakeSocket.opened = [];
  recordWaits(t);
  const { api } = setup();
  api.on("POST", "/v1/browsers/br_1/live_control", json(VIEW(1, { control: true })), json(VIEW(2, { control: true })));
  const view = nc.Browser.fromId("br_1").view({ control: true, WebSocket: Socket });
  const first = await opened(1);
  first.open();
  first.show();
  view.send({ type: "tap", x: 1, y: 1 });
  first.end(1011);
  view.send({ type: "tap", x: 2, y: 2 });  // between connections: dropped
  const second = await opened(2);
  second.open();
  view.send({ type: "tap", x: 3, y: 3 });  // open again, but showing what it last showed: dropped
  second.show();
  view.send({ type: "tap", x: 4, y: 4 });
  assert.deepEqual(first.sent.slice(1).map((s) => JSON.parse(s).x), [1]);
  assert.deepEqual(second.sent.map((s) => JSON.parse(s)), [{ type: "auth", token: "tok_2" }, { type: "tap", x: 4, y: 4 }]);
  view.close();
});

test("a view turned away for too many waits half a minute, then opens again with a new token", async (t) => {
  FakeSocket.opened = [];
  const waits = recordWaits(t);
  t.mock.method(Math, "random", () => 0.12345);  // so half a minute, spread, isn't a whole number of milliseconds
  const { api } = setup();
  const minted = api.on("POST", "/v1/browsers/br_1/live_view", json(VIEW(1)), json(VIEW(2)));
  const ends: unknown[] = [];
  const view = nc.Browser.fromId("br_1").view({ WebSocket: Socket, onEnd: (e) => ends.push(e) });
  (await opened(1)).end(4429, "This browser already has 8 live views open.");
  await opened(2);
  assert.deepEqual(waits, [30_000 * (0.5 + 0.12345)]);
  assert.deepEqual(ends, []);
  assert.equal(minted.count, 2);
  view.close();
});

/** Every wait it sets before opening again (spread, so never a whole number of milliseconds), each run at once; the
 *  client's own timers keep theirs. */
function recordWaits(t: TestContext): number[] {
  const realSetTimeout = globalThis.setTimeout;
  const waits: number[] = [];
  t.mock.method(Math, "random", () => 0.1234);
  t.mock.method(globalThis, "setTimeout", ((fn: () => void, ms?: number) => {
    if (ms === undefined || Number.isInteger(ms)) return realSetTimeout(fn, ms);
    waits.push(ms);
    return realSetTimeout(fn, 0);
  }) as typeof setTimeout);
  return waits;
}

test("it opens again with a new token: at once when it ran its time, after a wait when it dropped", async (t) => {
  FakeSocket.opened = [];
  const waits = recordWaits(t);
  const { api } = setup();
  const minted = api.on("POST", "/v1/browsers/br_1/live_view", ...[1, 2, 3, 4].map((n) => json(VIEW(n))));
  const states: string[] = [];
  const view = nc.Browser.fromId("br_1").view({ WebSocket: Socket, onState: (s) => states.push(s) });
  const first = await opened(1);
  first.open();
  first.show();
  first.end(4000, "renew");
  const second = await opened(2);
  assert.equal(waits.length, 0, "renewed at once");
  assert.equal(view.state, "live", "still live while it renews");
  second.open();
  assert.deepEqual(JSON.parse(second.sent[0]), { type: "auth", token: "tok_2" });
  second.show();
  second.end(1011, "lost");
  const third = await opened(3);
  assert.deepEqual(waits, [311.7]);
  third.open();
  third.end(1006);  // dropped before it showed anything: the wait grows
  await opened(4);
  assert.deepEqual(waits, [311.7, 623.4]);
  assert.equal(minted.count, 4);
  assert.deepEqual(states, ["live", "connecting"]);
  view.close();
});

test("the wait starts over only once a view stayed up thirty seconds", async (t) => {
  FakeSocket.opened = [];
  const waits = recordWaits(t);
  let now = 1_000_000;
  t.mock.method(Date, "now", () => now);
  const { api } = setup();
  api.on("POST", "/v1/browsers/br_1/live_view", ...[1, 2, 3, 4].map((n) => json(VIEW(n))));
  const view = nc.Browser.fromId("br_1").view({ WebSocket: Socket });
  const first = await opened(1);
  first.open();
  first.show();
  first.end(1011);
  const second = await opened(2);
  second.open();
  second.show();
  now += 29_000;
  second.end(1011);  // up 29 s: the wait keeps climbing
  const third = await opened(3);
  third.open();
  third.show();
  now += 30_000;
  third.end(1011);  // up 30 s: it starts over
  await opened(4);
  assert.deepEqual(waits, [311.7, 623.4, 311.7]);
  view.close();
});

test("a refused token is tried once more; refused again, or a final close, it ends", async (t) => {
  recordWaits(t);
  for (const code of [4404, 4409, 4410, 1008]) {
    FakeSocket.opened = [];
    const { api } = setup();
    api.on("POST", "/v1/browsers/br_1/live_view", json(VIEW(1)), json(VIEW(2)));
    const ends: unknown[] = [];
    const view = nc.Browser.fromId("br_1").view({ WebSocket: Socket, onEnd: (e) => ends.push(e) });
    const socket = await opened(1);
    socket.open();
    socket.end(code, "why");
    await tick();
    assert.deepEqual(ends, [{ code, reason: "why" }], String(code));
    assert.equal(view.state, "ended");
    assert.equal(FakeSocket.opened.length, 1);
  }

  FakeSocket.opened = [];
  const { api } = setup();
  const minted = api.on("POST", "/v1/browsers/br_1/live_view", ...[1, 2, 3].map((n) => json(VIEW(n))));
  const ends: unknown[] = [];
  nc.Browser.fromId("br_1").view({ WebSocket: Socket, onEnd: (e) => ends.push(e) });
  (await opened(1)).end(4401, "used");
  (await opened(2)).end(4401, "used");
  await tick();
  assert.deepEqual(ends, [{ code: 4401, reason: "used" }]);
  assert.equal(minted.count, 2);
});

test("a token call refused for good ends the view; a server's error is tried again", async (t) => {
  recordWaits(t);
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/browsers/br_1/live_view", apiError(403, "permission_denied", "Not for an MCP connection."));
  const ends: { code: number; reason: string }[] = [];
  nc.Browser.fromId("br_1").view({ WebSocket: Socket, onEnd: (e) => ends.push(e) });
  for (let i = 0; i < 20 && !ends.length; i++) await tick();
  assert.equal(ends[0]?.code, 0);
  assert.match(ends[0]?.reason ?? "", /MCP/);
  assert.equal(FakeSocket.opened.length, 0);

  const again = setup();
  const minted = again.api.on("POST", "/v1/browsers/br_1/live_view", apiError(503, "not_available"), json(VIEW(1)));
  const view = nc.Browser.fromId("br_1").view({ WebSocket: Socket });
  await opened(1);
  assert.equal(minted.count, 2);
  view.close();
});

test("a token never goes to a socket that isn't wss://", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/browsers/br_1/live_view", json(VIEW(1, { url: "https://evil.example/socket" })));
  const ends: { code: number; reason: string }[] = [];
  nc.Browser.fromId("br_1").view({ WebSocket: Socket, onEnd: (e) => ends.push(e) });
  for (let i = 0; i < 20 && !ends.length; i++) await tick();
  assert.match(ends[0]?.reason ?? "", /wss:\/\//);
  assert.equal(FakeSocket.opened.length, 0);
});
