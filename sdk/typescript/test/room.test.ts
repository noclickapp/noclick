// Room: a token from POST /v1/rooms/{room}/tokens, then a socket that is the page's place in the room. The socket
// offers only the protocol's name and sends the token as its first frame, presence and answers ride it, a reconnect
// resumes after the last event, and only what retrying can't fix ends it.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, BASE, json, setup } from "./helpers.ts";

const TOKEN = (n: number, access = "edit") => ({
  object: "room_token", room: "workflow:wf-1", url: `wss://api.test/v1/rooms/socket/rm_${n}?ticket=tk_${n}`,
  token: `tok_${n}`, access, member: { id: "u1", name: "Ana" }, expires_at: "2026-11-25T10:01:00Z",
  connection_ends_at: "2026-11-25T10:15:00Z",
});

class FakeSocket {
  static opened: FakeSocket[] = [];
  readonly sent: string[] = [];
  readyState = 1;
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
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
  frames(): Array<Record<string, unknown>> {
    return this.sent.filter((s) => s !== "ping").map((s) => JSON.parse(s));
  }
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const member = (id: string, user: string, data = {}) => ({ id, user: { id: user, name: user }, color: "#F87171", data, joined_at: 1 });

async function opened(n: number): Promise<FakeSocket> {
  for (let i = 0; i < 200 && FakeSocket.opened.length < n; i++) await tick();
  const socket = FakeSocket.opened[n - 1];
  assert.ok(socket, `socket ${n} opened`);
  await tick();
  return socket;
}

const Socket = FakeSocket as unknown as typeof WebSocket;

test("join sends the token first, resolves once in, and keeps everyone's presence", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  const minted = api.on("POST", "/v1/rooms/workflow%3Awf-1/tokens", json(TOKEN(1), { status: 201 }));
  const joining = nc.Room.join("workflow:wf-1", { WebSocket: Socket, origin: "https://app.example", presence: { cursor: null } });
  const socket = await opened(1);
  assert.equal(socket.url, "wss://api.test/v1/rooms/socket/rm_1?ticket=tk_1");
  assert.deepEqual(socket.protocols, ["noclick.room"], "only the protocol's name rides the header");
  assert.deepEqual(socket.frames()[0], { type: "auth", token: "tok_1" });
  assert.deepEqual(minted.last.body, { origin: "https://app.example" });
  socket.receive({ type: "ready", member: member("m_me", "u1"), members: [member("m_me", "u1"), member("m_bo", "bo")],
                   access: "edit", ends_at: Math.floor(Date.now() / 1000) + 900, runs: [], resumed: false });
  const room = await joining;
  assert.equal(room.access, "edit");
  assert.deepEqual(socket.frames()[1], { type: "presence", data: { cursor: null } }, "what it said as it joined");

  const seen: string[][] = [];
  room.on("presence", (members) => seen.push(members.map((m) => `${m.user?.id}:${JSON.stringify(m.data)}`)));
  socket.receive({ type: "presence", change: "update", member: member("m_bo", "bo", { cursor: { x: 1, y: 2 } }) });
  socket.receive({ type: "presence", change: "leave", member: member("m_bo", "bo") });
  assert.deepEqual(seen, [["u1:{}", 'bo:{"cursor":{"x":1,"y":2}}'], ["u1:{}"]]);

  room.presence.set({ selection: ["n1"] });
  room.broadcast("ai_editing.start", { nodeIds: ["n1"] });
  room.stop("run-1");
  assert.deepEqual(socket.frames().slice(-3), [
    { type: "presence", data: { selection: ["n1"] } },
    { type: "broadcast", event: "ai_editing.start", data: { nodeIds: ["n1"] } },
    { type: "stop", execution: "run-1" },
  ]);
  room.leave();
  assert.equal(socket.closedWith, 1000);
  assert.equal(room.status, "stopped");
});

test("the server's events and others' broadcasts are heard; a reconnect resumes after the last event", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/rooms/workflow%3Awf-1/tokens", json(TOKEN(1), { status: 201 }), json(TOKEN(2), { status: 201 }));
  const joining = nc.Room.join("workflow:wf-1", { WebSocket: Socket });
  const first = await opened(1);
  first.receive({ type: "ready", member: member("m_me", "u1"), members: [], access: "view", runs: [], resumed: false });
  const room = await joining;
  const events: nc.RoomEvent[] = [];
  const marks: unknown[] = [];
  room.on("event", (e) => events.push(e));
  room.on("ai_editing.start", (data, from) => marks.push([data, from]));
  first.receive({ type: "event", id: "c_g_1", event: "workflow:graph_changed", data: { version: 2 }, from: null });
  first.receive({ type: "broadcast", event: "ai_editing.start", data: { nodeIds: ["n1"] }, from: "m_bo" });
  assert.deepEqual(events.map((e) => [e.id, e.event, e.data, e.from]), [["c_g_1", "workflow:graph_changed", { version: 2 }, null]]);
  assert.deepEqual(marks, [[{ nodeIds: ["n1"] }, "m_bo"]]);
  first.end(4000, "lifetime");
  const second = await opened(2);
  assert.equal(second.url, "wss://api.test/v1/rooms/socket/rm_2?ticket=tk_2&after=c_g_1");
  room.leave();
});

test("a page answers what the server asks it, and a refusal of the token ends the join", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  api.on("POST", "/v1/rooms/owner/tokens", json(TOKEN(1, "own"), { status: 201 }));
  const joining = nc.Room.join("owner", { WebSocket: Socket });
  const socket = await opened(1);
  socket.receive({ type: "ready", member: member("m_me", "u1"), members: [], access: "own", runs: [], resumed: false });
  const room = await joining;
  room.answer("canvas.get_selected", (args) => ({ nodes: ["n1"], asked: args }));
  room.scope("wf-1");
  assert.deepEqual(socket.frames().slice(-2), [
    { type: "answers", names: ["canvas.get_selected"] }, { type: "scope", workflow: "wf-1" },
  ]);
  socket.receive({ type: "ask", id: "a1", name: "canvas.get_selected", args: { x: 1 } });
  await tick();
  assert.deepEqual(socket.frames().at(-1), { type: "answer", id: "a1", result: { nodes: ["n1"], asked: { x: 1 } } });
  room.leave();

  api.on("POST", "/v1/rooms/workflow%3Awf-2/tokens", apiError(404, "not_found", "No workflow."));
  await assert.rejects(nc.Room.join("workflow:wf-2", { WebSocket: Socket }), (err: nc.NoClickError) => err.status === 404);
});

test("a public chat page's visitor joins their thread's room with no key, through the link", async () => {
  FakeSocket.opened = [];
  const { api } = setup();
  const minted = api.on("POST", "/v1/public/agent_links/lnk_1/room", json({ ...TOKEN(7, "view"), room: "agent_link:lnk_1" }, { status: 201 }));
  const link = new nc.AgentLink("lnk_1", { visitor: "9a1f6c1e-0b6e-4c43-9d3f-1c7c2b8a9e10", baseUrl: BASE, fetch: api.fetch });
  const joining = link.join({ chat: "support", WebSocket: Socket });
  const socket = await opened(1);
  assert.deepEqual(socket.frames()[0], { type: "auth", token: "tok_7" });
  assert.deepEqual(minted.last.body, { chat: "support" });
  assert.equal(minted.last.headers.get("authorization"), null, "the link is the capability: no key goes");
  assert.equal(minted.last.headers.get("noclick-visitor"), "9a1f6c1e-0b6e-4c43-9d3f-1c7c2b8a9e10");
  socket.receive({ type: "ready", member: member("m_v", "visitor:1"), members: [], access: "view",
                   ends_at: Math.floor(Date.now() / 1000) + 900, runs: [], resumed: false });
  const room = await joining;
  assert.equal(room.access, "view");
  const heard: unknown[] = [];
  room.on("event", (event) => heard.push([event.event, event.data]));
  socket.receive({ type: "event", id: "e1", event: "chat:message", data: { conversation_id: "ck:wf:agent:share:lnk_1:v:support", message: "Hi" }, from: null });
  assert.deepEqual(heard, [["chat:message", { conversation_id: "ck:wf:agent:share:lnk_1:v:support", message: "Hi" }]]);
  room.leave();
});
