// Pausing a user's spending, the error a paused user's calls throw, and the message a deny rule gives,
// against the mock API.
import assert from "node:assert/strict";
import { test } from "node:test";

import { errorFromPayload } from "../src/errors.ts";
import * as nc from "../src/index.ts";
import { USER_ID, json, listing, setup, userRow } from "./helpers.ts";

const PAUSED = {
  paused: true, message: "You've used your credits.", action: { label: "Top up", url: "https://acme.test/top-up/user_42" },
  since: "2026-10-02T09:00:00Z", held: 2, paused_by: "key_1",
};

test("pause sends what the user is told, as the account, and reads the state back", async () => {
  const { api } = setup();
  api.on("GET", `/v1/users/${USER_ID}`, json(userRow({ spending: { paused: false, held: 0 } })));
  const pause = api.on("POST", `/v1/users/${USER_ID}/spending/pause`, json(userRow({ spending: PAUSED })));
  const user = nc.User.fromId(USER_ID);
  await user.hydrate();
  assert.equal(user.spending?.paused, false);

  await user.pauseSpending({ message: "You've used your credits.", action: { label: "Top up", url: "https://acme.test/top-up/{{user.id}}" } });
  assert.deepEqual(pause.last.body, {
    message: "You've used your credits.", action: { label: "Top up", url: "https://acme.test/top-up/{{user.id}}" },
  });
  assert.equal(pause.last.headers.get("noclick-user"), null);
  const spending = user.spending!;
  assert.deepEqual([spending.paused, spending.message, spending.action, spending.held, spending.pausedBy],
    [true, "You've used your credits.", { label: "Top up", url: "https://acme.test/top-up/user_42" }, 2, "key_1"]);
  assert.equal(spending.since?.toISOString(), "2026-10-02T09:00:00.000Z");

  await nc.User.fromId(USER_ID).pauseSpending();
  assert.deepEqual(pause.last.body, {});
});

test("resume, and the paused filter", async () => {
  const { api } = setup();
  const resume = api.on("POST", `/v1/users/${USER_ID}/spending/resume`, json(userRow({ spending: { paused: false, held: 0 } })));
  const user = await nc.User.fromId(USER_ID).resumeSpending();
  assert.equal(user.spending?.paused, false);
  assert.equal(resume.calls.length, 1);

  const list = api.on("GET", "/v1/users", json(listing([userRow({ spending: PAUSED })])));
  const paused = await nc.User.list({ spending: "paused" });
  assert.deepEqual(paused.map((u) => u.id), [USER_ID]);
  assert.equal(list.last.query.get("spending"), "paused");
  await nc.User.list({ status: "active" });
  assert.equal(list.last.query.get("spending"), null);
});

test("a paused user's call throws with their message apart from yours", () => {
  const err = errorFromPayload({
    error: {
      type: "spending_paused", message: "Spending is paused for user_42.",
      next_step: "Resume it with user.resume_spending() once they've paid.",
      user_message: "You've used your credits.", action: { label: "Top up", url: "https://acme.test/top-up/user_42" },
      since: "2026-10-02T09:00:00Z",
    },
  }, { status: 402 }) as nc.SpendingPaused;
  assert.ok(err instanceof nc.SpendingPaused);
  assert.deepEqual([err.status, err.userMessage, err.action], [402, "You've used your credits.", { label: "Top up", url: "https://acme.test/top-up/user_42" }]);
  assert.equal(err.since?.getUTCFullYear(), 2026);
  assert.equal(errorFromPayload({ type: "spending_paused", message: "m" }).constructor, nc.SpendingPaused);
  assert.equal((errorFromPayload({ type: "spending_paused", message: "m" }) as nc.SpendingPaused).action, undefined);
});

test("a deny rule carries its message, and only a deny rule may", async () => {
  const { api } = setup();
  const put = api.on("PUT", "/v1/policy", (call) => json({ object: "policy", user_id: null, ...(call.body as object) }));
  const rule = new nc.Rule("search", { when: 'user.metadata.plan == "free"', message: "Web search comes with Pro." });
  const policy = await nc.Policy.set({ deny: [rule, { tool: "gmail.*", message: "Email is a Pro feature." }] });
  assert.deepEqual((put.last.body as { deny: unknown }).deny, [
    { tool: "search", when: 'user.metadata.plan == "free"', message: "Web search comes with Pro." },
    { tool: "gmail.*", message: "Email is a Pro feature." },
  ]);
  assert.equal((policy.deny[0] as nc.Rule).message, "Web search comes with Pro.");
  await assert.rejects(nc.Policy.set({ allow: [rule] }), /Only a deny rule has a message/);
});
