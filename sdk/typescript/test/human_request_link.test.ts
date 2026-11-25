// A human request's page through its link (`HumanRequestLink`): it reads and answers with the link alone, never a key,
// the link's own key (`k`) going along with every call, and a request the link can't open rejects as not found.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { BASE, MockApi, apiError, json } from "./helpers.ts";

const PATH = "/v1/public/human_requests/hr_1";
const PAGE = {
  id: "hr_1", kind: "approve", status: "pending", message: "Buy +1 415 555 0100 for $1.15 a month?",
  expires_at: "2026-11-26T10:00:00+00:00", brand: { name: "NoClick" }, approval: { id: "ap_1" },
};

test("HumanRequestLink reads and answers with the link alone, its key going along", async () => {
  const api = new MockApi();
  const read = api.on("GET", PATH, json(PAGE));
  const answered = api.on("POST", `${PATH}/answer`, json({ ...PAGE, status: "answered" }));
  const link = new nc.HumanRequestLink("hr_1", { key: "k-1", baseUrl: BASE, fetch: api.fetch });
  const page = await link.read();
  assert.deepEqual([page.id, page.kind, page.status, page.message], ["hr_1", "approve", "pending", PAGE.message]);
  assert.equal(page.expiresAt?.toISOString(), "2026-11-26T10:00:00.000Z");
  assert.deepEqual(page.raw.approval, { id: "ap_1" });
  assert.equal(read.last.query.get("k"), "k-1");
  assert.equal(read.last.headers.get("Authorization"), null);
  const result = await link.answer({ decision: "approve" });
  assert.equal(result.status, "answered");
  assert.deepEqual(answered.last.body, { decision: "approve" });
  assert.equal(answered.last.query.get("k"), "k-1");
  assert.equal(answered.last.headers.get("Authorization"), null);
});

test("HumanRequestLink connects, replies and hands back; one the link can't open is NotFound", async () => {
  const api = new MockApi();
  const connected = api.on("POST", `${PATH}/connect`, json({ url: "https://accounts.example.test/sign-in" }));
  const replied = api.on("POST", `${PATH}/reply`, json(PAGE));
  const back = api.on("POST", `${PATH}/hand_back`, json(PAGE));
  const link = new nc.HumanRequestLink("hr_1", { baseUrl: BASE, fetch: api.fetch });
  assert.deepEqual(await link.connect({ credentialType: "gmail_oauth" }), { url: "https://accounts.example.test/sign-in" });
  assert.deepEqual(connected.last.body, { credential_type: "gmail_oauth" });
  assert.equal(connected.last.query.get("k"), null);
  await link.reply("I'll take it from here.");
  assert.deepEqual(replied.last.body, { text: "I'll take it from here." });
  await link.handBack();
  assert.equal(back.calls.length, 1);
  const gone = new MockApi();
  gone.on("GET", "/v1/public/human_requests/hr_2", apiError(404, "not_found", "No human request with that id."));
  await assert.rejects(new nc.HumanRequestLink("hr_2", { baseUrl: BASE, fetch: gone.fetch }).read(), nc.NotFound);
});
