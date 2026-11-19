// Review of the SDK's browser view: each finding a test that failed on the code it reviewed.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const URL_ = "wss://api.test/v1/browsers/live_views/attach";
const VIEW = (n: number) => ({
  object: "browser_live_view", browser_id: "br_1", control: true, thumb: false, url: URL_, token: `tok_${n}`,
  token_expires_at: "2026-11-19T10:02:00Z",
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
  readonly url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.opened.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {}
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  show() {
    this.onmessage?.({ data: JSON.stringify({ type: "viewport", width: 1280, height: 800 }) });
    this.onmessage?.({ data: new Uint8Array([0xff, 0xd8]).buffer });
  }
  end(code: number) {
    this.readyState = 3;
    this.onclose?.({ code, reason: "" });
  }
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function opened(n: number): Promise<FakeSocket> {
  for (let i = 0; i < 400 && FakeSocket.opened.length < n; i++) await tick();
  const socket = FakeSocket.opened[n - 1];
  assert.ok(socket, `socket ${n} opened`);
  return socket;
}

test("test_review_FINDING_queued_input_replays_blind_into_a_reconnected_control_view", async (t) => {
  // The waits before opening again run at once.
  const realSetTimeout = globalThis.setTimeout;
  t.mock.method(globalThis, "setTimeout", ((fn: () => void, ms?: number) =>
    realSetTimeout(fn, ms !== undefined && !Number.isInteger(ms) ? 0 : ms)) as typeof setTimeout);
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/browsers/br_1/live_control", json(VIEW(1)), json(VIEW(2)));
  const view = nc.Browser.fromId("br_1").view({ control: true, WebSocket: FakeSocket as unknown as typeof WebSocket });

  const first = await opened(1);
  first.open();
  first.show();
  first.end(1011); // the connection drops; the page keeps showing its last picture

  // Meanwhile the person taps where "Pay" was on that picture, and types.
  view.send({ type: "tap", x: 640, y: 360 });
  view.send({ type: "text", text: "4242 4242 4242 4242" });

  const second = await opened(2);
  second.open(); // authenticated, but the page as it is now hasn't been shown
  const sentBeforeAnyPicture = second.sent.map((s) => JSON.parse(s).type);
  view.close();
  assert.deepEqual(sentBeforeAnyPicture, ["auth"],
    "a tap and typing from a dropped view were replayed into the new one before it showed the page as it is now");
});
