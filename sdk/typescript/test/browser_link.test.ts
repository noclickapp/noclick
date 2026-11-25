// A person's page for a browser through its link (`BrowserLink`): it reads the link, starts a sign-in's browser, types
// and finishes with the link alone, never a key; one that stopped working rejects; and its view is the browser's own
// live view over the link's socket, which takes no token.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { BASE, apiError, json, setup } from "./helpers.ts";

const ID = "5d2f1c0b-7a9e-4c3d-8b6a-1f0e9d8c7b6a";
const PATH = `/v1/public/browser_links/${ID}`;
const LINK = {
  object: "browser_link", id: ID, purpose: "login", status: "open", domain: "portal.example.com",
  reason: "To download your invoices.", expires_at: "2026-10-03T00:00:00+00:00",
  brand: { name: "Acme Travel", logo_url: "https://cdn.acme.test/logo.png", color: "#1a73e8", support_url: null },
};

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
  show() {
    this.onmessage?.({ data: JSON.stringify({ type: "viewport", width: 390, height: 844 }) });
    this.onmessage?.({ data: new Uint8Array([0xff, 0xd8]).buffer });
  }
  end(code: number, reason = "") {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
}

const Socket = FakeSocket as unknown as typeof WebSocket;
/** Once what's already resolved has run: a view opens its socket after its (resolved) address. */
const settled = () => new Promise((resolve) => setImmediate(resolve));

test("BrowserLink reads, starts, types and finishes with the link alone", async () => {
  const { api } = setup();
  const read = api.on("GET", PATH, json(LINK));
  const started = api.on("POST", `${PATH}/start`, json({ ...LINK, status: "live" }));
  const typed = api.on("POST", `${PATH}/type`, json({ object: "browser_link", id: ID, typed: true }));
  const done = api.on("POST", `${PATH}/done`, json({ ...LINK, status: "done" }));
  const link = new nc.BrowserLink(ID, { baseUrl: BASE, fetch: api.fetch });

  const page = await link.read();
  assert.deepEqual([page.id, page.purpose, page.status, page.domain, page.reason],
    [ID, "login", "open", "portal.example.com", "To download your invoices."]);
  assert.equal(page.expiresAt?.toISOString(), "2026-10-03T00:00:00.000Z");
  assert.deepEqual(page.brand, { name: "Acme Travel", logoUrl: "https://cdn.acme.test/logo.png", color: "#1a73e8", supportUrl: null });
  assert.deepEqual(page.raw, LINK);
  assert.equal((await link.start()).status, "live");
  await link.type({ text: "482913" });
  await link.type({ key: "Enter" });
  assert.equal((await link.done()).status, "done");

  assert.deepEqual(typed.calls.map((call) => call.body), [{ text: "482913" }, { key: "Enter" }]);
  assert.deepEqual(started.last.body, {});
  for (const call of [read.last, started.last, ...typed.calls, done.last]) {
    assert.equal(call.headers.get("authorization"), null, "the link is the capability: no key goes");
  }
});

test("a link that stopped working rejects in its own words; a read that failed is asked again", async () => {
  const { api } = setup();
  api.on("POST", `${PATH}/done`, apiError(409, "not_available", "This link no longer works."));
  api.on("GET", "/v1/public/browser_links/gone", apiError(404, "not_found", "This link no longer works."));
  const reads = api.on("GET", PATH, apiError(503, "not_available"), json(LINK));
  await assert.rejects(new nc.BrowserLink(ID, { baseUrl: BASE, fetch: api.fetch }).done(),
    (err: nc.NoClickError) => err instanceof nc.NotAvailable && err.message === "This link no longer works.");
  await assert.rejects(new nc.BrowserLink("gone", { baseUrl: BASE, fetch: api.fetch }).read(), nc.NotFound);
  const once = new nc.BrowserLink(ID, { baseUrl: BASE, fetch: api.fetch, maxRetries: 1, backoffMs: 0 });
  assert.equal((await once.read()).status, "open");
  assert.equal(reads.count, 2);
});

test("its view opens the link's socket with no token, shows the page and takes a person's input", async () => {
  FakeSocket.opened = [];
  const seen: unknown[] = [];
  const view = new nc.BrowserLink(ID, { baseUrl: BASE }).view({
    WebSocket: Socket, onViewport: (v) => seen.push(v), onPicture: (jpeg) => seen.push(Array.from(jpeg)),
    onState: (state) => seen.push(state),
  });
  await settled();
  const [socket] = FakeSocket.opened;
  assert.equal(socket.url, `wss://api.test${PATH}/view`);
  assert.equal(view.control, true, "a full-size view drives the page");
  socket.open();
  view.send({ type: "tap", x: 1, y: 1 }); // before the page shows: dropped
  socket.show();
  view.send({ type: "key", key: "Enter" });
  assert.deepEqual(socket.sent.map((s) => JSON.parse(s)), [{ type: "key", key: "Enter" }], "no auth frame: the link admits it");
  assert.deepEqual(seen, [{ width: 390, height: 844 }, "live", [0xff, 0xd8]]);
  view.close();
  assert.equal(socket.closedWith, 1000);
});

test("a thumbnail only watches; a dropped view opens again, and one whose link stopped working ends", async () => {
  FakeSocket.opened = [];
  const ends: unknown[] = [];
  const states: string[] = [];
  const link = new nc.BrowserLink(ID, { baseUrl: "http://localhost:8000" });
  const tile = link.view({ thumb: true, WebSocket: Socket, onEnd: (end) => ends.push(end), onState: (s) => states.push(s) });
  await settled();
  const [socket] = FakeSocket.opened;
  assert.equal(socket.url, `ws://localhost:8000${PATH}/view?size=thumb`);
  assert.equal(tile.control, false);
  assert.throws(() => tile.send({ type: "tap", x: 1, y: 1 }), /only watches/);
  socket.open();
  socket.show();
  socket.end(1011);
  assert.deepEqual([states, ends], [["live", "connecting"], []], "dropped: it opens again by itself");
  tile.close();

  const full = link.view({ WebSocket: Socket, onEnd: (end) => ends.push(end) });
  await settled();
  FakeSocket.opened[1].end(4410, "This link no longer works.");
  assert.deepEqual(ends, [{ code: 4410, reason: "This link no longer works." }]);
  assert.equal(full.state, "ended");
});
