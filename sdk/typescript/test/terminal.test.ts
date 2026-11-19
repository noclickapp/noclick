// Take-over: a coding agent's conversation as its harness's own terminal. `takeOver` opens it (a single-use token for
// a websocket), `terminal` reads where it stands, `handBack` gives it back; `connect` speaks the websocket: the token
// in its first message (never the URL), what's typed as binary, a resize as text, and the take-over's moves.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "coder", model: "claude-sonnet-4-5", harness: "claude_code", instructions: "hi",
  tools: [], user_id: null, created_at: "2026-10-29T10:00:00Z",
};
const TAKEN = {
  object: "terminal", agent_id: "ag_1", conversation: "main", harness: "claude_code", state: "person",
  waiting_for_turn: false, since: "2026-10-29T10:01:00Z", ends_at: "2026-10-29T13:57:00Z", idle_limit_s: 900,
  detached_limit_s: 300, ended_because: null, url: "wss://api.test/v1/terminals/attach", token: "tok_1",
  token_expires_at: "2026-10-29T10:03:00Z",
};

test("take over, read where it stands, hand back", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const take = api.on("POST", "/v1/agents/ag_1/conversations/main/terminal", json(TAKEN));
  const read = api.on("GET", "/v1/agents/ag_1/conversations/main/terminal", json({ ...TAKEN, url: undefined, token: undefined }));
  const back = api.on("DELETE", "/v1/agents/ag_1/conversations/main/terminal",
    json({ ...TAKEN, state: "agent", ended_because: "handed_back", url: undefined, token: undefined }));
  const coder = nc.Agent.fromId("ag_1");

  const terminal = await coder.takeOver("main", { interrupt: true, cols: 120, rows: 36 });
  assert.deepEqual(take.last.body, { interrupt: true, cols: 120, rows: 36 });
  assert.deepEqual([terminal.state, terminal.harness, terminal.url, terminal.token, terminal.idleLimitS],
    ["person", "claude_code", "wss://api.test/v1/terminals/attach", "tok_1", 900]);
  assert.equal(terminal.endsAt?.toISOString(), "2026-10-29T13:57:00.000Z");
  await coder.takeOver("main");
  assert.deepEqual(take.last.body, {});  // its turn finishes first unless asked to interrupt

  const now = await coder.terminal("main");
  assert.equal(read.count, 1);
  assert.deepEqual([now.state, now.token], ["person", null]);
  assert.throws(() => now.connect(), /take it over/);  // no token: nothing to open

  await now.handBack();
  assert.equal(back.count, 1);
  assert.deepEqual([now.state, now.endedBecause], ["agent", "handed_back"]);
});

class FakeSocket {
  static last: FakeSocket;
  readonly sent: (string | Uint8Array)[] = [];
  binaryType = "blob";
  onopen?: () => void;
  onmessage?: (event: { data: unknown }) => void;
  onclose?: (event: { code: number; reason: string }) => void;
  closedWith?: number;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.last = this;
  }
  send(data: string | Uint8Array) {
    this.sent.push(data);
  }
  close(code: number) {
    this.closedWith = code;
  }
  // The server's side.
  receive(data: string | ArrayBuffer) {
    this.onmessage?.({ data });
  }
  end(code: number, reason = "") {
    this.onclose?.({ code, reason });
  }
}

test("connect sends the token first, holds what's typed until it's ready, and reports each move", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("POST", "/v1/agents/ag_1/conversations/main/terminal", json(TAKEN));
  const terminal = await nc.Agent.fromId("ag_1").takeOver("main");
  const seen: { data: string[]; states: string[]; closed: { code: number; final: boolean }[]; ready: number } = {
    data: [], states: [], closed: [], ready: 0 };
  const connection = terminal.connect({
    cols: 100, rows: 30, WebSocket: FakeSocket as unknown as typeof WebSocket,
    onData: (bytes) => seen.data.push(new TextDecoder().decode(bytes)),
    onReady: () => seen.ready++,
    onState: (status) => seen.states.push(`${status.state}:${status.reason ?? ""}`),
    onClose: ({ code, final }) => seen.closed.push({ code, final }),
  });
  const socket = FakeSocket.last;
  assert.equal(socket.url, "wss://api.test/v1/terminals/attach");  // no token in the URL
  assert.equal(socket.binaryType, "arraybuffer");
  socket.onopen?.();
  // It can renew (it takes over again for a new token), and says so.
  assert.deepEqual(JSON.parse(socket.sent[0] as string), { type: "auth", token: "tok_1", cols: 100, rows: 30, renew: true });

  connection.write("ls\r");  // before it's ready: held
  connection.resize(120, 40);  // before it's ready: nothing to size
  assert.equal(socket.sent.length, 1);
  socket.receive(JSON.stringify({ type: "ready", state: "person" }));
  assert.equal(seen.ready, 1);
  assert.deepEqual(new TextDecoder().decode(socket.sent[1] as Uint8Array), "ls\r");
  connection.write(new Uint8Array([3]));
  assert.deepEqual(socket.sent[2], new Uint8Array([3]));
  connection.resize(120, 40);
  assert.deepEqual(JSON.parse(socket.sent[3] as string), { type: "resize", cols: 120, rows: 40 });

  socket.receive(new TextEncoder().encode("hello\r\n").buffer as ArrayBuffer);
  assert.deepEqual(seen.data, ["hello\r\n"]);
  socket.receive(JSON.stringify({ type: "state", state: "handing_back", reason: "handed_back" }));
  socket.receive(JSON.stringify({ type: "state", state: "agent", reason: "handed_back" }));
  socket.end(nc.TERMINAL_CLOSED_FOR_GOOD.ended, "The agent has the conversation again.");
  assert.deepEqual(seen.states, ["handing_back:handed_back", "agent:handed_back"]);
  assert.deepEqual(seen.closed, [{ code: 4410, final: true }]);
  assert.throws(() => terminal.connect({ WebSocket: FakeSocket as unknown as typeof WebSocket }), /once/);
});

test("a lost connection isn't final: take over again for a new token", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  api.on("POST", "/v1/agents/ag_1/conversations/main/terminal", json(TAKEN), json({ ...TAKEN, token: "tok_2" }));
  const coder = nc.Agent.fromId("ag_1");
  const closes: boolean[] = [];
  (await coder.takeOver("main")).connect({ WebSocket: FakeSocket as unknown as typeof WebSocket, onClose: ({ final }) => closes.push(final) });
  FakeSocket.last.end(1011, "lost");
  assert.deepEqual(closes, [false]);
  const again = await coder.takeOver("main");
  again.connect({ WebSocket: FakeSocket as unknown as typeof WebSocket });
  FakeSocket.last.onopen?.();
  assert.equal(JSON.parse(FakeSocket.last.sent[0] as string).token, "tok_2");
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test("asked to renew, a terminal takes over again and answers with the new token; the session goes on", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const take = api.on("POST", "/v1/agents/ag_1/conversations/main/terminal", json(TAKEN), json({ ...TAKEN, token: "tok_2" }));
  const connection = (await nc.Agent.fromId("ag_1").takeOver("main")).connect({ WebSocket: FakeSocket as unknown as typeof WebSocket });
  const socket = FakeSocket.last;
  socket.onopen?.();
  socket.receive(JSON.stringify({ type: "ready", state: "person" }));
  socket.receive(JSON.stringify({ type: "renew" }));
  await settle();
  assert.equal(take.count, 2);
  assert.equal(take.last.body, null);  // taking over again, asking nothing: never interrupts the agent
  assert.deepEqual(JSON.parse(socket.sent.at(-1) as string), { type: "renew", token: "tok_2" });
  socket.receive(JSON.stringify({ type: "renewed" }));
  connection.write("ls\r");  // the same connection, still open
  assert.equal(new TextDecoder().decode(socket.sent.at(-1) as Uint8Array), "ls\r");
});

test("a terminal with no way to renew doesn't say it renews, and a close at its time isn't final", async () => {
  const closes: { code: number; final: boolean }[] = [];
  const connection = new nc.TerminalConnection("wss://api.test/v1/terminals/attach", "tok_1", {
    WebSocket: FakeSocket as unknown as typeof WebSocket, onClose: ({ code, final }) => closes.push({ code, final }) });
  const socket = FakeSocket.last;
  socket.onopen?.();
  assert.equal(JSON.parse(socket.sent[0] as string).renew, undefined);  // it can't renew, so it has no lifetime
  socket.receive(JSON.stringify({ type: "ready", state: "open" }));
  socket.receive(JSON.stringify({ type: "renew" }));
  await settle();
  assert.equal(socket.sent.length, 1);  // the auth alone: nothing to renew with
  socket.end(nc.TERMINAL_RENEW, "It wasn't renewed in time: open it again.");
  assert.deepEqual(closes, [{ code: 4000, final: false }]);
  connection.close();
});

test("a renew that can't get a token, or comes after the terminal closed, sends nothing", async () => {
  let asked = 0;
  new nc.TerminalConnection("wss://api.test/v1/terminals/attach", "tok_1", {
    WebSocket: FakeSocket as unknown as typeof WebSocket,
    renew: async () => { asked++; throw new Error("offline"); },
  });
  let socket = FakeSocket.last;
  socket.onopen?.();
  socket.receive(JSON.stringify({ type: "ready", state: "open" }));
  socket.receive(JSON.stringify({ type: "renew" }));
  await settle();
  assert.deepEqual([asked, socket.sent.length], [1, 1]);

  let release!: (token: string) => void;
  new nc.TerminalConnection("wss://api.test/v1/terminals/attach", "tok_1", {
    WebSocket: FakeSocket as unknown as typeof WebSocket,
    renew: () => new Promise<string>((resolve) => { release = resolve; }),
  });
  socket = FakeSocket.last;
  socket.onopen?.();
  socket.receive(JSON.stringify({ type: "ready", state: "open" }));
  socket.receive(JSON.stringify({ type: "renew" }));
  socket.end(4410, "The shell ended.");
  release("tok_late");
  await settle();
  assert.equal(socket.sent.length, 1);
});
