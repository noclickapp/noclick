import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, setup, userRow } from "./helpers.ts";
import type { Call } from "./helpers.ts";

// --- policy ------------------------------------------------------------------

test("Policy.get/put for the account send no user", async () => {
  const { api } = setup();
  const get = api.on("GET", "/v1/policy", json({ object: "policy", user_id: null, allow: [], deny: ["*.delete_*"], require_approval: ["gmail.send_email"] }));
  const put = api.on("PUT", "/v1/policy", (call: Call) => json({ object: "policy", user_id: null, ...(call.body as object) }));
  const policy = await nc.Policy.get();
  assert.deepEqual([policy.userId, policy.allow, policy.deny, policy.requireApproval], [null, [], ["*.delete_*"], ["gmail.send_email"]]);
  assert.equal(get.last.query.get("user_id"), null);
  assert.equal(get.last.headers.get("NoClick-User"), null);

  const saved = await nc.Policy.set({ deny: ["slack.*"] });
  assert.deepEqual(put.last.body, { allow: [], deny: ["slack.*"], require_approval: [] });
  assert.deepEqual(saved.deny, ["slack.*"]);
});

test("a user policy sends your id for the user (a string or a User) with no lookup; asUser applies like everywhere", async () => {
  const { api } = setup();
  const get = api.on("GET", "/v1/policy", json({ object: "policy", user_id: USER_ID, allow: ["search"], deny: [], require_approval: [] }));
  const put = api.on("PUT", "/v1/policy", json({ object: "policy", user_id: USER_ID }));
  const lookup = api.on("GET", `/v1/users/${USER_ID}`, json(userRow()));

  await nc.Policy.get({ user: USER_ID });
  assert.equal(get.last.query.get("user_id"), USER_ID);
  assert.equal(get.last.headers.get("NoClick-User"), null);

  await nc.Policy.set({ allow: ["search"] }, { user: nc.User.fromId(USER_ID) });
  assert.deepEqual(put.last.body, { user_id: USER_ID, allow: ["search"], deny: [], require_approval: [] });
  assert.equal(put.last.headers.get("NoClick-User"), null);
  assert.equal(lookup.count, 0);

  // asUser addresses that user's policy, in the body (a key acting for a user can't write policy)
  await nc.asUser("user_9", () => nc.Policy.set({ deny: ["*.delete_*"] }));
  assert.deepEqual(put.last.body, { user_id: "user_9", allow: [], deny: ["*.delete_*"], require_approval: [] });
  assert.equal(put.last.headers.get("NoClick-User"), null);
  await nc.asUser("user_9", () => nc.Policy.get());
  assert.equal(get.last.query.get("user_id"), "user_9");
  assert.equal(get.last.headers.get("NoClick-User"), null);
  // an explicit null still means the account's, and an explicit user still wins
  await nc.asUser("user_9", () => nc.Policy.set({ deny: ["slack.*"] }, { user: null }));
  assert.deepEqual(put.last.body, { allow: [], deny: ["slack.*"], require_approval: [] });
  await nc.asUser("user_9", () => nc.Policy.get({ user: USER_ID }));
  assert.equal(get.last.query.get("user_id"), USER_ID);
});

// --- brand + usage -----------------------------------------------------------

test("Brand.get/put", async () => {
  const { api } = setup();
  api.on("GET", "/v1/brand", json({ object: "brand", name: "Acme", logo_url: "https://a/logo.png", color: "#123456", support_url: null, email_from_name: "Acme" }));
  const put = api.on("PUT", "/v1/brand", (call: Call) => json({ object: "brand", ...(call.body as object) }));
  const brand = await nc.Brand.get();
  assert.deepEqual([brand.name, brand.logoUrl, brand.color, brand.supportUrl], ["Acme", "https://a/logo.png", "#123456", null]);
  const saved = await nc.asUser("user_1", () => nc.Brand.set({ name: "Acme", color: "#ff0000", emailFromName: "Acme Team" }));
  assert.deepEqual(put.last.body, { name: "Acme", logo_url: null, color: "#ff0000", support_url: null, email_from_name: "Acme Team" });
  assert.equal(put.last.headers.get("NoClick-User"), null); // one brand per account
  assert.equal(saved.emailFromName, "Acme Team");
});

test("Brand.update sends only what changes", async () => {
  const { api } = setup();
  const patch = api.on("PATCH", "/v1/brand", json({ object: "brand", name: "Acme", color: "#000000", support_url: null }));
  const saved = await nc.Brand.update({ color: "#000000", supportUrl: null });
  assert.deepEqual(patch.last.body, { color: "#000000", support_url: null }); // left out stays; null clears
  assert.equal(patch.last.headers.get("NoClick-User"), null);
  assert.equal(saved.color, "#000000");
});

test("Brand oauthApps name your own app per provider", async () => {
  const { api } = setup();
  const app = "6f1c2a4e-0b8d-4c55-9a43-2f0e9d7b1a11";
  const put = api.on("PUT", "/v1/brand", json({
    object: "brand", name: "Acme", oauth_apps: { google: app },
    oauth_redirect_urls: { google: "https://noclick.com/api/auth/google/callback" },
  }));
  const brand = await nc.Brand.set({ name: "Acme", oauthApps: { google: app } });
  assert.deepEqual((put.last.body as { oauth_apps: unknown }).oauth_apps, { google: app });
  assert.deepEqual(brand.oauthApps, { google: app });
  assert.ok(brand.oauthRedirectUrls.google.endsWith("/api/auth/google/callback"));

  const patch = api.on("PATCH", "/v1/brand", json({ object: "brand", oauth_apps: {}, oauth_redirect_urls: {} }));
  await nc.Brand.update({ oauthApps: { google: null } }); // back to NoClick's app; other providers kept
  assert.deepEqual(patch.last.body, { oauth_apps: { google: null } });
  await nc.Brand.update({ oauthApps: null });
  assert.deepEqual(patch.last.body, { oauth_apps: null });
});

test("Usage.get groups spend", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/usage", json({
    object: "usage", period: "2026-09", total_usd: 12.5, group_by: "user",
    groups: [{ id: USER_ID, usd: 10, events: 40 }, { id: null, usd: 2.5, events: 3 }],
  }));
  const usage = await nc.Usage.get({ groupBy: "user" });
  assert.equal(usage.totalUsd, 12.5);
  assert.deepEqual(usage.groups.map((g) => [g.id, g.usd, g.events]), [[USER_ID, 10, 40], [null, 2.5, 3]]);
  assert.equal(route.last.query.get("period"), "month");
  assert.equal(route.last.query.get("group_by"), "user");
  // An id that spent nothing is $0 with no events.
  assert.deepEqual([usage.group(USER_ID).usd, usage.group("nobody").usd, usage.group("nobody").events], [10, 0, 0]);
  await nc.Usage.get({ groupBy: "user", agent: nc.Agent.fromId("agt_1") });
  assert.equal(route.last.query.get("agent_id"), "agt_1");
});

test("usage groups by the person each charge was for, by name", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/usage", json({
    object: "usage", period: "2026-09", total_usd: 12.5, group_by: "person",
    groups: [{ id: "login-ana", name: "Ana", usd: 9, events: 30 }, { id: null, name: null, usd: 3.5, events: 2 }],
  }));
  const usage = await nc.usage({ groupBy: "person" });
  assert.equal(route.last.query.get("group_by"), "person");
  assert.deepEqual(usage.groups.map((g) => [g.id, g.name, g.usd]), [["login-ana", "Ana", 9], [null, null, 3.5]]);
  assert.deepEqual([usage.group("login-ana").name, usage.group("nobody").name], ["Ana", null]);
});

test("usage groups by workstream, by name", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/usage", json({
    object: "usage", period: "2026-09", total_usd: 12.5, group_by: "workstream",
    groups: [{ id: "ws_1", name: "Bakery site", usd: 9, events: 30 }, { id: null, name: null, usd: 3.5, events: 2 }],
  }));
  const usage = await nc.usage({ groupBy: "workstream" });
  assert.equal(route.last.query.get("group_by"), "workstream");
  assert.deepEqual(usage.groups.map((g) => [g.id, g.name, g.usd]), [["ws_1", "Bakery site", 9], [null, null, 3.5]]);
});

test("workstreams are listed with their spend and renamed by name or id", async () => {
  const { api } = setup();
  const row = { object: "workstream", id: "ws_1", name: "Bakery site", created_at: "2026-11-20T10:00:00+00:00", updated_at: "2026-11-20T10:00:00+00:00" };
  const listed = api.on("GET", "/v1/workstreams", json({ object: "list", unnamed_usd: 3.5, data: [{ ...row, spent_usd: 9, events: 30 }] }));
  const [site] = await nc.Workstream.list({ user: USER_ID });
  assert.equal(listed.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([site.id, site.name, site.spentUsd, site.events, site.createdAt?.getUTCFullYear()], ["ws_1", "Bakery site", 9, 30, 2026]);
  const renamed = api.on("PATCH", "/v1/workstreams/web%2Fsite%20old", json({ ...row, merged_from: { id: "ws_2", name: "Menu" } }));
  const merged = await nc.Workstream.rename("web/site old", "Bakery site");
  assert.deepEqual(renamed.last.body, { name: "Bakery site" });
  assert.equal(renamed.last.headers.get("NoClick-User"), null);
  assert.deepEqual([merged.id, merged.spentUsd, (merged.raw.merged_from as nc.JsonObject).name], ["ws_1", 0, "Menu"]);
  const byId = api.on("PATCH", "/v1/workstreams/ws_1", json({ ...row, name: "Bakery" }));
  assert.equal((await nc.Workstream.rename(site, "Bakery")).name, "Bakery");
  assert.equal(byId.count, 1);
});

test("a workstream is archived and brought back, and the archived ones are listed apart", async () => {
  const { api } = setup();
  const row = { object: "workstream", id: "ws_1", name: "Q3 launch", created_at: "2026-11-20T10:00:00+00:00", updated_at: "2026-11-20T10:00:00+00:00" };
  const change = api.on("PATCH", "/v1/workstreams/Q3%20launch", (call: Call) => json({ ...row, archived: (call.body as nc.JsonObject).archived }));
  const archived = await nc.Workstream.archive("Q3 launch");
  assert.deepEqual(change.last.body, { archived: true });
  assert.equal(change.last.headers.get("NoClick-User"), null);
  assert.equal(archived.archived, true);
  const listed = api.on("GET", "/v1/workstreams", json({ object: "list", unnamed_usd: 0, data: [{ ...row, archived: true, spent_usd: 2, events: 4 }] }));
  const [put] = await nc.Workstream.list({ archived: true });
  assert.equal(listed.last.query.get("archived"), "true");
  assert.deepEqual([put.id, put.archived, put.spentUsd], ["ws_1", true, 2]);
  await nc.Workstream.list();
  assert.equal(listed.last.query.get("archived"), null);
  const back = await nc.Workstream.unarchive("Q3 launch");
  assert.deepEqual(change.last.body, { archived: false });
  assert.equal(back.archived, false);
});

test("an operation and a coding agent's job name their workstream as it reads now", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_1", json({ object: "operation", id: "op_1", kind: "agent.task", status: "running", workstream: { id: "ws_1", name: "Bakery site" } }));
  api.on("GET", "/v1/operations/op_2", json({ object: "operation", id: "op_2", kind: "agent.task", status: "running", workstream: null }));
  assert.deepEqual((await nc.Operation.fromId("op_1").refresh()).workstream, { id: "ws_1", name: "Bakery site" });
  assert.equal((await nc.Operation.fromId("op_2").refresh()).workstream, null);
});

test("a spend cap refusal is SpendCapExceeded and is not retried", async () => {
  const { api, sleeps } = setup();
  const route = api.on("POST", "/v1/sandboxes", apiError(402, "spend_cap_exceeded", "User cap reached.", { cap: 5, spent: 5.01, scope: "user" }));
  await assert.rejects(nc.Sandbox.create(), (err: nc.SpendCapExceeded) => {
    assert.ok(err instanceof nc.SpendCapExceeded);
    assert.deepEqual([err.cap, err.spent, err.scope], [5, 5.01, "user"]);
    return true;
  });
  assert.equal(route.count, 1);
  assert.equal(sleeps.length, 0);
});

// --- channels ----------------------------------------------------------------

const CHANNEL = {
  object: "channel", id: "ch_1", name: "orders", mode: "mentions", status: "open", user_id: USER_ID,
  members: [{ id: "mem_1", type: "agent", agent_id: "agt_1" }, { id: "mem_2", type: "user" }],
  created_at: "2026-09-25T10:00:00Z",
};

function message(id: string, text: string) {
  return {
    object: "channel_message", id, channel_id: "ch_1", author: { type: "agent", id: "agt_1", name: "host" },
    text, mentions: [], created_at: "2026-09-25T10:00:00Z",
  };
}

test("Channel.create maps members and options", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/agt_1", json({ object: "agent", id: "agt_1", name: "host", user_id: null }));
  const create = api.on("POST", "/v1/channels", json(CHANNEL));
  const channel = await nc.asUser("user_42", () => nc.Channel.create("orders", {
    members: [nc.Agent.fromId("agt_1"), { agentId: "agt_2" }, "user", { a2aUrl: "https://peer/a2a", name: "Peer" }, "https://other/a2a"],
    mode: "all", maxAgentTurns: 6, maxMentionHops: 3, budgetUsd: 2,
  }));
  assert.deepEqual(create.last.body, {
    name: "orders",
    members: [
      { agent_id: "agt_1" }, { agent_id: "agt_2" }, { user: true }, { a2a_url: "https://peer/a2a", name: "Peer" },
      { a2a_url: "https://other/a2a" },
    ],
    mode: "all", max_agent_turns: 6, max_mention_hops: 3, budget_usd: 2,
  });
  assert.equal(create.last.headers.get("NoClick-User"), "user_42");
  assert.equal(channel.id, "ch_1");
  assert.equal(channel.members.length, 2);
  await assert.rejects(nc.Channel.create("x", { members: ["bob"] }), TypeError);
});

test("Channel.create leaves the mode to the server, whose default wakes every agent", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/channels", json({ ...CHANNEL, mode: "all" }));
  const channel = await nc.Channel.create("orders", { members: [{ agentId: "agt_1" }] });
  assert.equal("mode" in (create.last.body as object), false);
  assert.equal(channel.mode, "all");
});

test("Channel.create with a User member acts for that user", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/channels", json(CHANNEL));
  const user = nc.User.fromId(USER_ID);
  const channel = await nc.Channel.create("orders", { members: [{ agentId: "agt_1" }, user] });
  assert.deepEqual((create.last.body as { members: unknown }).members, [{ agent_id: "agt_1" }, { user: true }]);
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID);
  // Later calls act for the channel's user too.
  const post = api.on("POST", "/v1/channels/ch_1/messages", json({ object: "channel_message", id: "m1", channel_id: "ch_1", author: { type: "account" }, text: "hi" }));
  await channel.post("hi");
  assert.equal(post.last.headers.get("NoClick-User"), USER_ID);
  // Inside asUser the member still decides.
  await nc.asUser("user_9", () => nc.Channel.create("orders", { members: [user] }));
  assert.equal(create.last.headers.get("NoClick-User"), USER_ID);

  const other = nc.User.fromId("t2");
  await assert.rejects(nc.Channel.create("x", { members: [user, other] }), /one user/);
  await assert.rejects(nc.Channel.create("x", { members: [user], user: "user_9" }), /one user/);
  await assert.rejects(nc.Channel.create("x", { members: [user], user: null }), /one user/);
  assert.equal(create.count, 2);
});

test("post, long-poll messages, listen, members and close act for the channel's user", async () => {
  const { api } = setup();
  api.on("GET", "/v1/channels/ch_1", json(CHANNEL));
  const post = api.on("POST", "/v1/channels/ch_1/messages", (call: Call) =>
    json({ ...message("msg_1", (call.body as { text: string }).text), author: { type: "user", id: USER_ID, name: "Ana" } }));
  const poll = api.on(
    "GET", "/v1/channels/ch_1/messages",
    json(listing([message("msg_2", "Hi!"), message("msg_3", "Lemon cake?")])),
    json(listing([])),
    json(listing([message("msg_4", "Yes")])),
  );
  const add = api.on("POST", "/v1/channels/ch_1/members", json({ object: "channel_member", id: "mem_3", type: "a2a" }));
  const remove = api.on("DELETE", "/v1/channels/ch_1/members/mem_3", json({ ok: true }));
  const close = api.on("POST", "/v1/channels/ch_1/close", json({ ...CHANNEL, status: "closed" }));

  const channel = await nc.Channel.get("ch_1");
  const sent = await channel.post("@host what's on?", { as: "user" });
  assert.deepEqual(post.last.body, { text: "@host what's on?", as: { user: true } });
  assert.equal(sent.author.type, "user");
  assert.equal(post.last.headers.get("NoClick-User"), USER_ID);

  const first = await channel.messages({ after: "msg_1", waitS: 20, limit: 10 });
  assert.equal(poll.last.query.get("limit"), "10");
  assert.deepEqual(first.map((m) => m.text), ["Hi!", "Lemon cake?"]);
  assert.equal(poll.last.query.get("after"), "msg_1");
  assert.equal(poll.last.query.get("wait_s"), "20");
  assert.ok(first[0].createdAt instanceof Date);

  const seen: string[] = [];
  for await (const m of channel.stream({ after: "msg_3", waitS: 1 })) {
    seen.push(m.id);
    break;
  }
  assert.deepEqual(seen, ["msg_4"]);
  assert.deepEqual(poll.calls.slice(1).map((c) => c.query.get("after")), ["msg_3", "msg_3"]);

  const member = await channel.add({ a2aUrl: "https://peer/a2a" });
  assert.deepEqual(add.last.body, { a2a_url: "https://peer/a2a" });
  await channel.remove(member);
  assert.equal(remove.count, 1);
  assert.equal((await channel.close()).status, "closed");
  assert.equal(close.count, 1);
});

// --- sandboxes ---------------------------------------------------------------

const SANDBOX = { object: "sandbox", id: "sbx_1", status: "running", expires_at: "2026-09-25T10:10:00Z", user_id: null };

test("sandbox create, exec, files, list and terminate", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/sandboxes", json(SANDBOX));
  const exec = api.on("POST", "/v1/sandboxes/sbx_1/exec", json({ stdout: "3\n", stderr: "", exit_code: 0 }));
  const put = api.on("PUT", "/v1/sandboxes/sbx_1/files", json({ ok: true }));
  const get = api.on("GET", "/v1/sandboxes/sbx_1/files", new Response(new TextEncoder().encode("print(1 + 2)\n"), {
    headers: { "content-type": "application/octet-stream" },
  }));
  const list = api.on("GET", "/v1/sandboxes", json(listing([SANDBOX])));
  const del = api.on("DELETE", "/v1/sandboxes/sbx_1", json({ ...SANDBOX, status: "terminated" }));

  const sandbox = await nc.asUser("user_42", () => nc.Sandbox.create({ image: "python", timeoutS: 600, memoryMb: 512, network: false }));
  assert.deepEqual(create.last.body, { image: "python", timeout_s: 600, memory_mb: 512, network: false });
  assert.equal(sandbox.status, "running");
  assert.ok(sandbox.expiresAt instanceof Date);

  await sandbox.files.write("main.py", "print(1 + 2)\n");
  assert.equal(put.last.query.get("path"), "main.py");
  assert.equal(put.last.body, "print(1 + 2)\n");
  assert.equal(put.last.headers.get("Content-Type"), "application/octet-stream");
  assert.equal(put.last.headers.get("NoClick-User"), "user_42"); // captured at create

  const bytes = await sandbox.files.read("main.py");
  assert.ok(bytes instanceof Uint8Array);
  assert.equal(await sandbox.files.readText("main.py"), "print(1 + 2)\n");
  assert.equal(get.count, 2);

  const result = await sandbox.exec("python main.py", { timeoutS: 30 });
  assert.deepEqual([result.stdout, result.stderr, result.exitCode], ["3\n", "", 0]);
  assert.deepEqual(exec.last.body, { command: "python main.py", timeout_s: 30 });

  const [listed] = await nc.Sandbox.list({ status: "live" });
  assert.equal(listed.id, "sbx_1");
  assert.equal(list.last.query.get("status"), "live");
  assert.equal(list.last.headers.get("NoClick-User"), null);

  await sandbox.terminate();
  assert.equal(sandbox.status, "terminated");
  assert.equal(del.count, 1);
});

test("a sandbox's shell is a terminal token for its own user's sandbox", async () => {
  const { api } = setup();
  const opened = api.on("POST", "/v1/sandboxes/sbx_1/shell", json({
    object: "sandbox_shell", sandbox_id: "sbx_1", url: "wss://api.test/v1/terminals/attach", token: "tok_1",
    token_expires_at: "2026-09-25T10:02:00Z", idle_limit_s: 900,
  }));
  const shell = await nc.Sandbox.fromId("sbx_1", { user: "user_42" }).shell();
  assert.deepEqual([shell.sandboxId, shell.url, shell.token, shell.idleLimitS], ["sbx_1", "wss://api.test/v1/terminals/attach", "tok_1", 900]);
  assert.ok(shell.tokenExpiresAt instanceof Date);
  assert.equal(opened.last.headers.get("NoClick-User"), "user_42");
});

test("a non-zero exit is a result, not an error", async () => {
  const { api } = setup();
  api.on("POST", "/v1/sandboxes/sbx_1/exec", json({ stdout: "", stderr: "boom", exit_code: 2 }));
  const result = await nc.Sandbox.fromId("sbx_1").exec("exit 2");
  assert.equal(result.exitCode, 2);
  assert.equal(result.stderr, "boom");
});
