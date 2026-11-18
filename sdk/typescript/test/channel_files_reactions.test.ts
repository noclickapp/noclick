// Channels' files, voice clips, reactions, history paging, topic and read point; a workspace's logo.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const CHANNEL = {
  object: "channel", id: "ch_1", name: "launch", topic: "Friday's launch", mode: "mentions", status: "open", halt_reason: null,
  unread_count: 3, user_id: null, workspace_id: null, members: [{ id: "mem_1", type: "agent", agent_id: "agt_s", name: "Scout" }],
};
const CLIP = {
  object: "channel_attachment", id: "att_2", channel_id: "ch_1", name: "Voice clip.mp3", mime_type: "audio/mpeg", size_bytes: 9000,
  kind: "audio", url: "https://assets.test/u/account/att_2/Voice%20clip.mp3", voice: true, duration_ms: 4200, peaks: [0.2, 1],
};

function message(fields: Record<string, unknown> = {}) {
  return {
    object: "channel_message", id: "m1", channel_id: "ch_1", author: { type: "account", id: null, name: "owner" }, text: "hi",
    mentions: [], created_at: "2026-10-09T10:00:00Z", attachments: [], reactions: [], ...fields,
  };
}

test("a voice clip uploads its bytes with its name, type and waveform, then posts with the message", async () => {
  const { api } = setup();
  const upload = api.on("POST", "/v1/channels/ch_1/attachments", json(CLIP, { status: 201 }));
  const post = api.on("POST", "/v1/channels/ch_1/messages", json(message({ text: "", attachments: [CLIP] }), { status: 201 }));
  const room = nc.Channel.fromId("ch_1");
  const blob = new Blob([new Uint8Array([1, 2, 3])], { type: "audio/webm" });
  const clip = await room.upload(blob, { name: "Voice clip.webm", voice: true, peaks: [0.2, 1] });
  assert.deepEqual([upload.last.query.get("name"), upload.last.query.get("mime_type"), upload.last.query.get("voice"), upload.last.query.get("peaks")], [
    "Voice clip.webm", "audio/webm", "true", "0.2,1",
  ]);
  assert.equal(upload.last.body, blob);
  assert.deepEqual([clip.kind, clip.voice, clip.durationMs, clip.peaks, clip.mimeType], ["audio", true, 4200, [0.2, 1], "audio/mpeg"]);

  const posted = await room.post("", { files: [clip] });
  assert.deepEqual(post.last.body, { text: "", attachments: ["att_2"] });
  assert.equal(posted.attachments[0].url, CLIP.url);
  await assert.rejects(() => room.upload(new Uint8Array([1])), /Name a file/);
});

test("reactions add and take back, as the account or a member", async () => {
  const { api } = setup();
  const reacted = message({ reactions: [{ emoji: "🎉", count: 2, by: [{ type: "account", id: null, name: "owner" }, { type: "agent", id: "agt_s", name: "Scout" }] }] });
  api.on("GET", "/v1/channels/ch_1", json(CHANNEL));
  const add = api.on("POST", "/v1/channels/ch_1/messages/m1/reactions", json(reacted));
  const remove = api.on("DELETE", `/v1/channels/ch_1/messages/m1/reactions/${encodeURIComponent("🎉")}`, json(message()));
  const room = await nc.Channel.get("ch_1");
  const got = await room.react("m1", "🎉");
  assert.deepEqual(add.last.body, { emoji: "🎉" });
  assert.deepEqual(got.reactions.map((r) => [r.emoji, r.count, r.by.map((b) => b.name)]), [["🎉", 2, ["owner", "Scout"]]]);
  await room.react(got, "🎉", { as: { agentId: "agt_s" } });
  assert.deepEqual(add.last.body, { emoji: "🎉", as: { agent_id: "agt_s" } });
  assert.deepEqual((await room.unreact(got, "🎉")).reactions, []);
  assert.equal([...remove.last.query.keys()].length, 0);
  await room.unreact("m1", "🎉", { as: { agentId: "agt_s" } });
  assert.equal(remove.last.query.get("agent_id"), "agt_s");
});

test("history reads back from the newest, page by page, and one message reads as it now is", async () => {
  const { api } = setup();
  const list = api.on("GET", "/v1/channels/ch_1/messages", json(listing([message({ id: "m4" }), message({ id: "m5" })], "m4")));
  api.on("GET", "/v1/channels/ch_1/messages/m5", json(message({ id: "m5" })));
  const room = nc.Channel.fromId("ch_1");
  const page = await room.messagesPage({ newest: true, limit: 2 });
  assert.deepEqual([list.last.query.get("newest"), list.last.query.get("limit"), page.nextCursor], ["true", "2", "m4"]);
  await room.messages({ before: page.nextCursor ?? undefined, limit: 2 });
  assert.equal(list.last.query.get("before"), "m4");
  assert.equal((await room.message("m5")).id, "m5");
  await assert.rejects(() => room.messages({ after: "m1", newest: true }), /one of after, before or newest/);
});

test("topic, update and the account's read point", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/channels", json(CHANNEL, { status: 201 }));
  const patch = api.on("PATCH", "/v1/channels/ch_1", json({ ...CHANNEL, topic: "Post-launch", mode: "all" }));
  const read = api.on("POST", "/v1/channels/ch_1/read", json({ ...CHANNEL, unread_count: 0 }));
  const room = await nc.Channel.create("launch", { topic: "Friday's launch" });
  assert.deepEqual(create.last.body, { name: "launch", topic: "Friday's launch" });
  assert.deepEqual([room.topic, room.unreadCount], ["Friday's launch", 3]);
  await room.update({ topic: "Post-launch", mode: "all" });
  assert.deepEqual(patch.last.body, { topic: "Post-launch", mode: "all" });
  assert.deepEqual([room.topic, room.mode], ["Post-launch", "all"]);
  await room.update({ name: "launch-day" });
  assert.deepEqual(patch.last.body, { name: "launch-day" });
  assert.equal((await room.markRead()).unreadCount, 0);
  assert.deepEqual(read.last.body, {});
  await room.markRead("m2");
  assert.deepEqual(read.last.body, { message_id: "m2" });
});

test("a workspace takes a logo upload", async () => {
  const { api } = setup();
  const WS = { object: "workspace", id: "ws_1", name: "Acme", logo_url: null, user_id: null, status: "active", members: [] };
  const put = api.on("PUT", "/v1/workspaces/ws_1/logo", json({ ...WS, logo_url: "https://assets.test/logo.png" }));
  const acme = nc.Workspace.fromId("ws_1");
  const image = new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });
  assert.equal((await acme.setLogo(image)).logoUrl, "https://assets.test/logo.png");
  assert.equal(put.last.query.get("mime_type"), "image/png");
  await assert.rejects(() => acme.setLogo(new Uint8Array([1])), /mimeType/);
});
