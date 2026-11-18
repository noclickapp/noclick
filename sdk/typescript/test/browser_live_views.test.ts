// A browser watched from the conversation it works in: found by its agent and conversation, read as what each
// step did (never what it typed) and whom it waits on, taken over and handed back.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const BROWSER = {
  object: "browser", id: "br_1", status: "running", agent_id: "ag_1", conversation: "owner",
  live_url: "https://noclick.test/live/lk_1", act_id: "op_9", acting: true, held: false, waiting_on: null,
  steps: [{ action: "type", target: "Email", at: "2026-11-14T10:00:02Z" }],
  frame_url: "https://files.noclick.test/last-page.jpg",
  created_at: "2026-11-14T10:00:00Z", started_at: "2026-11-14T10:00:01Z",
};

test("a conversation's browser, as the people watching it read it", async () => {
  const { api } = setup();
  const list = api.on("GET", "/v1/browsers", json(listing([BROWSER])));
  const [browser] = await nc.Browser.list({ agent: "ag_1", conversation: "owner", limit: 1 });
  assert.equal(list.last.query.get("agent_id"), "ag_1");
  assert.equal(list.last.query.get("conversation"), "owner");
  assert.equal(browser.conversation, "owner");
  assert.equal(browser.actId, "op_9");
  assert.equal(browser.acting, true);
  assert.deepEqual(browser.steps, [{ action: "type", target: "Email", at: new Date("2026-11-14T10:00:02Z") }]);
  assert.equal(browser.startedAt?.toISOString(), "2026-11-14T10:00:01.000Z");
  assert.equal(browser.waitingOn, null);
  assert.equal(browser.frameUrl, "https://files.noclick.test/last-page.jpg");
});

test("taking a browser over and handing it back", async () => {
  const { api } = setup();
  const waiting = { person: "Sign in to shop.example.com.", for_you: true };
  const take = api.on("POST", "/v1/browsers/br_1/take_over", json({ ...BROWSER, status: "parked", held: true, waiting_on: waiting }));
  const give = api.on("POST", "/v1/browsers/br_1/hand_back", json({ ...BROWSER, held: false }));
  const browser = nc.Browser.fromId("br_1");
  await browser.takeOver();
  assert.equal(take.count, 1);
  assert.equal(browser.held, true);
  assert.deepEqual(browser.waitingOn, { person: "Sign in to shop.example.com.", forYou: true });
  await browser.handBack();
  assert.equal(give.count, 1);
  assert.equal(browser.held, false);
  assert.equal(browser.status, "running");
});
