// Channels' threads, pins, bookmarks, files and links, and deleting a channel to the trash.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const OWNER = { type: "account", id: null, name: "owner" };
const WRITER = { type: "agent", id: "agt_w", name: "Writer" };

function message(fields: Record<string, unknown> = {}) {
  return {
    object: "channel_message", id: "m1", channel_id: "ch_1", author: OWNER, text: "hi", mentions: [],
    created_at: "2026-11-10T10:00:00Z", attachments: [], reactions: [], thread_id: null, also_in_channel: false,
    reply_count: 0, last_reply_at: null, reply_authors: [], following: false, unread_replies: 0, pinned: null, ...fields,
  };
}

test("a reply goes in its thread, and the thread reads back like the timeline", async () => {
  const { api } = setup();
  const post = api.on("POST", "/v1/channels/ch_1/messages", json(message({ id: "r1", thread_id: "m1" }), { status: 201 }));
  const replies = api.on("GET", "/v1/channels/ch_1/messages/m1/replies", json(listing([message({ id: "r1", thread_id: "m1" })], "r1")));
  const room = nc.Channel.fromId("ch_1");
  const reply = await room.reply("m1", "Tuesday works.", { alsoInChannel: true });
  assert.deepEqual(post.last.body, { text: "Tuesday works.", thread_id: "m1", also_in_channel: true });
  assert.equal(reply.threadId, "m1");
  await room.post("Notes go out Monday.", { thread: reply });
  assert.deepEqual(post.last.body, { text: "Notes go out Monday.", thread_id: "r1" });
  await room.post("Top level.");
  assert.deepEqual(post.last.body, { text: "Top level." });

  const page = await room.repliesPage("m1", { newest: true, limit: 10 });
  assert.deepEqual([replies.last.query.get("newest"), replies.last.query.get("limit"), page.nextCursor], ["true", "10", "r1"]);
  assert.deepEqual((await room.replies(reply)).map((r) => r.id), ["r1"]);
  await assert.rejects(() => room.replies("m1", { after: "r1", newest: true }), /one of after, before or newest/);
});

test("a message carries its thread's counts and its pin", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels/ch_1/messages/m1", json(message({
    reply_count: 2, last_reply_at: "2026-11-10T11:00:00Z", reply_authors: [WRITER, OWNER], following: true, unread_replies: 1,
    mentions: ["channel"], pinned: { by: WRITER, at: "2026-11-10T12:00:00Z" },
  })));
  const got = await nc.Channel.fromId("ch_1").message("m1");
  assert.deepEqual([got.replyCount, got.following, got.unreadReplies, got.mentions], [2, true, 1, ["channel"]]);
  assert.deepEqual(got.replyAuthors.map((a) => a.name), ["Writer", "owner"]);
  assert.equal(got.lastReplyAt?.toISOString(), "2026-11-10T11:00:00.000Z");
  assert.deepEqual([got.pinned?.by.name, got.pinned?.at?.toISOString()], ["Writer", "2026-11-10T12:00:00.000Z"]);
  assert.equal(got.threadId, null);
});

test("read, follow and the threads you follow across channels", async () => {
  const { api } = setup();
  const read = api.on("POST", "/v1/channels/ch_1/messages/m1/read", json(message({ following: true })));
  api.on("POST", "/v1/channels/ch_1/messages/m1/follow", json(message({ following: true })));
  api.on("DELETE", "/v1/channels/ch_1/messages/m1/follow", json(message()));
  const threads = api.on("GET", "/v1/channels/threads", json(listing([{
    object: "channel_thread", id: "m1", channel_id: "ch_1", channel_name: "launch", workspace_id: "ws_1",
    parent: message({ reply_count: 2 }), latest_reply: message({ id: "r2", thread_id: "m1", author: WRITER }),
    reply_count: 2, unread_count: 1, following: true, last_reply_at: "2026-11-10T11:00:00Z",
  }])));
  const room = nc.Channel.fromId("ch_1");
  await room.markThreadRead("m1", "r1");
  assert.deepEqual(read.last.body, { reply_id: "r1" });
  await room.markThreadRead("m1");
  assert.deepEqual(read.last.body, {});
  assert.equal((await room.follow("m1")).following, true);
  assert.equal((await room.unfollow("m1")).following, false);

  const [thread] = await nc.Channel.threads({ unread: true, workspace: "ws_1" });
  assert.deepEqual([threads.last.query.get("unread"), threads.last.query.get("workspace_id")], ["true", "ws_1"]);
  assert.deepEqual([thread.channelName, thread.parent.id, thread.latestReply?.author.name, thread.unreadCount, thread.replyCount],
    ["launch", "m1", "Writer", 1, 2]);
  const page = await nc.Channel.threadsPage({ limit: 1 });
  assert.equal(page.data.length, 1);
});

test("pins and bookmarks", async () => {
  const { api } = setup();
  const pin = api.on("POST", "/v1/channels/ch_1/messages/m1/pin", json(message({ pinned: { by: WRITER, at: null } })));
  api.on("DELETE", "/v1/channels/ch_1/messages/m1/pin", json(message()));
  api.on("GET", "/v1/channels/ch_1/pins", json(listing([{ object: "channel_pin", message: message(), by: OWNER, at: "2026-11-10T12:00:00Z" }])));
  const bookmark = { object: "channel_bookmark", id: "bm_1", channel_id: "ch_1", title: "Launch plan", url: "https://docs.example.com/plan", by: OWNER, created_at: "2026-11-10T12:00:00Z" };
  const add = api.on("POST", "/v1/channels/ch_1/bookmarks", json(bookmark, { status: 201 }));
  api.on("GET", "/v1/channels/ch_1/bookmarks", json(listing([bookmark])));
  const patch = api.on("PATCH", "/v1/channels/ch_1/bookmarks/bm_1", json({ ...bookmark, title: "Plan" }));
  const remove = api.on("DELETE", "/v1/channels/ch_1/bookmarks/bm_1", json({ object: "channel_bookmark", id: "bm_1", deleted: true }));
  const room = nc.Channel.fromId("ch_1");

  assert.equal((await room.pin("m1", { as: { agentId: "agt_w" } })).pinned?.by.name, "Writer");
  assert.deepEqual(pin.last.body, { as: { agent_id: "agt_w" } });
  assert.equal((await room.unpin("m1")).pinned, null);
  const [pinned] = await room.pins();
  assert.deepEqual([pinned.message.id, pinned.by.name, pinned.at?.toISOString()], ["m1", "owner", "2026-11-10T12:00:00.000Z"]);

  const saved = await room.addBookmark({ url: "https://docs.example.com/plan", title: "Launch plan" });
  assert.deepEqual(add.last.body, { url: "https://docs.example.com/plan", title: "Launch plan" });
  assert.deepEqual([saved.id, saved.title, saved.by.name], ["bm_1", "Launch plan", "owner"]);
  assert.deepEqual((await room.bookmarks()).map((b) => b.url), ["https://docs.example.com/plan"]);
  assert.equal((await room.updateBookmark(saved, { title: "Plan" })).title, "Plan");
  assert.deepEqual(patch.last.body, { title: "Plan" });
  await room.removeBookmark("bm_1");
  assert.equal(remove.count, 1);
});

test("files, links and deleting to the trash", async () => {
  const { api } = setup();
  const file = { object: "channel_attachment", id: "att_1", name: "report.pdf", mime_type: "application/pdf", size_bytes: 10, kind: "file", url: "https://assets.test/report.pdf" };
  const files = api.on("GET", "/v1/channels/ch_1/files", json(listing([
    { object: "channel_file", message_id: "m1", thread_id: null, author: OWNER, created_at: "2026-11-10T10:00:00Z", file },
  ], "m1:1")));
  api.on("GET", "/v1/channels/ch_1/links", json(listing([
    { object: "channel_link", message_id: "m2", thread_id: "m1", author: WRITER, created_at: "2026-11-10T10:00:00Z", url: "https://docs.example.com/plan", title: "the plan", domain: "docs.example.com" },
  ])));
  api.on("DELETE", "/v1/channels/ch_1", json({
    object: "channel", id: "ch_1", deleted: true, restorable_until: "2026-12-10T10:00:00Z", operation_id: "op_1",
    trash: { object: "trash_item", id: "tr_1", kind: "channel", resource_id: "ch_1", name: "launch", user_id: null, trashed_at: "2026-11-10T10:00:00Z", purge_after: "2026-12-10T10:00:00Z" },
  }));
  const room = nc.Channel.fromId("ch_1");
  const page = await room.files({ q: "report", limit: 1 });
  assert.deepEqual([files.last.query.get("q"), files.last.query.get("limit"), page.nextCursor], ["report", "1", "m1:1"]);
  assert.deepEqual([page.data[0].file.name, page.data[0].author.name, page.data[0].threadId], ["report.pdf", "owner", null]);
  await room.files({ cursor: page.nextCursor });
  assert.equal(files.last.query.get("cursor"), "m1:1");
  const [link] = (await room.links()).data;
  assert.deepEqual([link.url, link.title, link.domain, link.threadId], ["https://docs.example.com/plan", "the plan", "docs.example.com", "m1"]);
  const trashed = await room.delete();
  assert.ok(trashed instanceof nc.TrashItem);
  assert.equal(trashed.id, "tr_1");
});

test("who joined or left reads as the channel's membership entry", async () => {
  const { api } = setup();
  const system = { type: "system", id: null, name: "NoClick" };
  api.on("GET", "/v1/channels/ch_1/messages", json(listing([
    message({ id: "j1", author: system, text: "owner added Writer.", event: {
      type: "membership", action: "added", by: OWNER,
      members: [{ id: "cm_1", type: "agent", name: "Writer", agent_id: "agt_w", user_id: null }] } }),
    message({ id: "j2", author: system, text: "Ana left.", event: {
      type: "membership", action: "removed", by: null,
      members: [{ id: "cm_2", type: "user", name: "Ana", agent_id: null, user_id: "ana" }] } }),
    message({ id: "p1", author: system, text: "owner pinned a message.", event: { type: "pinned", message_id: "m1" } }),
    message({ id: "m2" }),
  ])));
  const said = await nc.Channel.fromId("ch_1").messages();
  assert.deepEqual(said[0].membership, {
    action: "added", by: OWNER, members: [{ id: "cm_1", type: "agent", name: "Writer", agentId: "agt_w", userId: null }],
  });
  assert.deepEqual([said[1].membership?.action, said[1].membership?.by, said[1].membership?.members[0].userId],
    ["removed", null, "ana"]);
  assert.deepEqual([said[2].membership, said[3].membership], [null, null]);
});

test("star, mute, leave and reopen a channel", async () => {
  const { api } = setup();
  const CHANNEL = { object: "channel", id: "ch_1", name: "launch", status: "open", members: [], unread_count: 3 };
  api.on("GET", "/v1/channels/ch_1", json(CHANNEL));
  const room = await nc.Channel.get("ch_1");
  api.on("POST", "/v1/channels/ch_1/star", json({ ...CHANNEL, starred: true }));
  assert.equal((await room.star()).starred, true);
  api.on("DELETE", "/v1/channels/ch_1/star", json({ ...CHANNEL, starred: false }));
  assert.equal((await room.unstar()).starred, false);
  api.on("POST", "/v1/channels/ch_1/mute", json({ ...CHANNEL, muted: true, unread_count: 0 }));
  await room.mute();
  assert.deepEqual([room.muted, room.unreadCount], [true, 0]);
  api.on("DELETE", "/v1/channels/ch_1/mute", json({ ...CHANNEL, muted: false }));
  assert.equal((await room.unmute()).muted, false);
  const reopen = api.on("POST", "/v1/channels/ch_1/reopen", json({ ...CHANNEL, name: "launch-2" }));
  assert.equal((await room.reopen({ name: "launch-2" })).name, "launch-2");
  assert.deepEqual(reopen.last.body, { name: "launch-2" });
  const leave = api.on("POST", "/v1/channels/ch_1/leave", json({ object: "channel_member", id: "m1", deleted: true }));
  await room.leave();
  assert.equal(leave.calls.length, 1);
  api.on("POST", "/v1/channels/ch_1/join", json({ ...CHANNEL, muted: true, unread_count: 1, mention_count: 1 }));
  await room.join();
  assert.deepEqual([room.mentionCount, room.unreadCount], [1, 1]);
});

test("your own sections of your channels read, save against their version, and lose to a newer save", async () => {
  const { api } = setup();
  const LAYOUT = {
    object: "channel_sections", workspace_id: "ws_1", version: 2, folded: ["channels"], updated_at: "2026-11-14T10:00:00Z",
    sections: [{ id: "8f9c5a0e-3b0e-4b7f-9a59-3c6c3a2f1d10", name: "Launch", folded: true, channel_ids: ["ch_1", "ch_2"] }],
  };
  const read = api.on("GET", "/v1/channels/sections", json(LAYOUT));
  const layout = await nc.Channel.sections({ workspace: "ws_1" });
  assert.equal(read.last.query.get("workspace_id"), "ws_1");
  assert.deepEqual([layout.workspaceId, layout.version, layout.folded], ["ws_1", 2, ["channels"]]);
  assert.deepEqual(layout.sections, [{ id: LAYOUT.sections[0].id, name: "Launch", folded: true, channelIds: ["ch_1", "ch_2"] }]);

  const save = api.on("PUT", "/v1/channels/sections", json({ ...LAYOUT, version: 3, sections: [], folded: [] }));
  const saved = await nc.Channel.saveSections({ version: layout.version, sections: [] }, { workspace: "ws_1" });
  assert.deepEqual(save.last.body, { workspace_id: "ws_1", version: 2, sections: [], folded: [] });
  assert.equal(saved.version, 3);

  api.on("PUT", "/v1/channels/sections", json({ error: { type: "conflict", message: "Your sections changed.", version: 4 } }, { status: 409 }));
  await assert.rejects(
    () => nc.Channel.saveSections({ version: 3, sections: layout.sections, folded: ["starred"] }),
    (e: unknown) => e instanceof nc.Conflict && e.version === 4,
  );
});
