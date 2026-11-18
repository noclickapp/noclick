// A long conversation read back a page at a time, and a question to the owner withdrawn once it's answered another
// way.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup, USER_ID } from "./helpers.ts";

const AGENT = {
  object: "agent", id: "ag_1", name: "support", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", created_at: "2026-09-25T10:00:00Z",
};
const message = (text: string, at: number) => ({ role: "user", text, created_at: `2026-10-15T10:0${at}:00Z` });

test("history reads a long thread back a page at a time", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  let route = api.on("GET", "/v1/agents/ag_1/conversations/ticket-1841", json({
    object: "conversation", messages: [message("third", 3), message("fourth", 4)], next_cursor: "2",
  }));
  const support = nc.Agent.fromId("ag_1");
  const page = await support.historyPage("ticket-1841", { limit: 2 });
  assert.deepEqual([page.data.map((m) => m.text), page.nextCursor], [["third", "fourth"], "2"]);
  assert.deepEqual(Object.fromEntries(route.last.query), { limit: "2" });

  route = api.on("GET", "/v1/agents/ag_1/conversations/ticket-1841", json({
    object: "conversation", messages: [message("first", 1), message("second", 2)], next_cursor: null,
  }));
  const earlier = await support.historyPage("ticket-1841", { limit: 2, before: page.nextCursor! });
  assert.deepEqual(Object.fromEntries(route.last.query), { limit: "2", before: "2" });
  assert.deepEqual([earlier.data.map((m) => m.text), earlier.nextCursor], [["first", "second"], null]);

  // history() is the page's messages; without limit, the whole thread as before.
  assert.deepEqual((await support.history("ticket-1841", { limit: 2, before: "2" })).map((m) => m.text), ["first", "second"]);
  await support.history("ticket-1841");
  assert.deepEqual(Object.fromEntries(route.last.query), {});
});

test("a question to the owner is withdrawn with a note", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const withdraw = api.on("POST", "/v1/agents/ag_1/conversations/ticket%2F1841/withdraw_question", json({
    object: "question_withdrawal", agent_id: "ag_1", conversation: "ticket/1841", withdrawn: ["May I refund order 1841?"],
  }));
  const support = nc.Agent.fromId("ag_1");
  // Only the account withdraws one: no user goes with the call.
  const withdrawn = await nc.asUser(USER_ID, () => support.withdrawQuestion("ticket/1841", "Ana approved the refund on the phone; it's issued."));
  assert.deepEqual(withdrawn, ["May I refund order 1841?"]);
  assert.deepEqual(withdraw.last.body, { note: "Ana approved the refund on the phone; it's issued." });
  assert.equal(withdraw.last.headers.get("NoClick-User"), null);

  await support.withdrawQuestion("ticket/1841", "Handled by email.", { questionId: "req_2" });
  assert.deepEqual(withdraw.last.body, { note: "Handled by email.", question_id: "req_2" });

  api.on("POST", "/v1/agents/ag_1/conversations/ticket%2F1841/withdraw_question", apiError(409, "conflict", "No question to the owner waits in this conversation."));
  await assert.rejects(support.withdrawQuestion("ticket/1841", "Already answered."), nc.Conflict);
});

test("a notification passing on a space's news names its space", async () => {
  const { api } = setup();
  api.on("GET", "/v1/agents/ag_1", json(AGENT));
  const space = { workspace_id: "ws_1", name: "Launch", label: "NoClick · Launch" };
  api.on("GET", "/v1/agents/ag_1/conversations/owner", json({
    object: "conversation", next_cursor: null, messages: [
      { role: "assistant", text: "The import failed twice.", notification: true, space, created_at: "2026-11-11T10:00:00Z" },
      { role: "assistant", text: "Your site is live.", notification: true, created_at: "2026-11-11T10:01:00Z" },
      { role: "assistant", text: "Done.", created_at: "2026-11-11T10:02:00Z" },
    ],
  }));
  const said = await nc.Agent.fromId("ag_1").history("owner");
  assert.deepEqual(said.map((m) => [m.notification, m.space]), [
    [true, { workspaceId: "ws_1", name: "Launch", label: "NoClick · Launch" }], [true, null], [false, null],
  ]);
});
