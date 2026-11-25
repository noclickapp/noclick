import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, json, operation, setup } from "./helpers.ts";

const AGENT_ID = "8b7c5e2a-4d1f-4c3e-9a6b-1f2e3d4c5b6a";

test("Human.owner() reaches the owner as the account, on the app they text NoClick on", async () => {
  const { api } = setup();
  const send = api.on("POST", "/v1/humans/requests", json({ ...operation({ kind: "human.notify", status: "succeeded" }), request: {} }));
  await nc.asUser(USER_ID, () => nc.Human.owner().notify("The site is live", { via: ["whatsapp"] }));
  assert.deepEqual(send.last.body, { kind: "notify", to: { owner: true }, message: "The site is live", via: ["whatsapp"] });
  assert.equal(send.last.headers.get("NoClick-User"), null); // the owner is the account's, never a user's
});

test("answerWith routes the owner's texts to an agent in a conversation, and null hands them back", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/humans/owner/answer", json({ object: "human_answer", person: "owner", agent_id: AGENT_ID }));
  const owner = nc.Human.owner();
  await owner.answerWith(AGENT_ID, { conversation: "owner" });
  assert.deepEqual(route.last.body, { agent_id: AGENT_ID, conversation: "owner" });
  await owner.answerWith(null);
  assert.deepEqual(route.last.body, { agent_id: null });

  api.on("GET", "/v1/humans/owner/answer", json({ object: "human_answer", person: "owner", agent_id: AGENT_ID }));
  assert.equal((await owner.answering())?.id, AGENT_ID);
  await assert.rejects(new nc.Human({ email: "ana@example.com" }).answerWith(AGENT_ID), TypeError);
});

test("reach reads NoClick's numbers and whether a phone is linked, as the account", async () => {
  const { api } = setup();
  const read = api.on(
    "GET",
    "/v1/humans/owner/reach",
    json({
      object: "owner_reach",
      phone_linked: true,
      lines: [{ app: "whatsapp", number: "+14155550100" }, { app: "imessage", number: "+14155550101" }],
    }),
  );
  const reach = await nc.asUser(USER_ID, () => nc.Human.owner().reach());
  assert.equal(read.last.headers.get("NoClick-User"), null); // where the owner texts NoClick is the account's, never a user's
  assert.deepEqual(reach, {
    lines: [{ app: "whatsapp", number: "+14155550100" }, { app: "imessage", number: "+14155550101" }],
    phoneLinked: true,
    email: null,
  });
  api.on("GET", "/v1/humans/owner/reach", json({
    object: "owner_reach", lines: [], phone_linked: false,
    email: { address: "maya@noclick.email", paused: true, from_anyone: false },
  }));
  assert.deepEqual(await nc.Human.owner().reach(), {
    lines: [], phoneLinked: false, email: { address: "maya@noclick.email", paused: true, fromAnyone: false },
  });
  const placed = api.on("PUT", "/v1/humans/owner/timezone", json({ object: "owner_timezone", timezone: "Europe/London" }));
  await nc.Human.owner().setTimezone("Europe/London");
  assert.deepEqual(placed.last.body, { timezone: "Europe/London" });
  await assert.rejects(new nc.Human({ email: "ana@example.com" }).reach(), TypeError);
});

test("the owner claims and renames the address they email their assistant at", async () => {
  const { api } = setup();
  const claim = api.on("POST", "/v1/humans/owner/reach/email", json({
    object: "owner_email_address", address: "maya@noclick.email", paused: false, from_anyone: true,
  }));
  const owner = nc.Human.owner();
  assert.deepEqual(await nc.asUser(USER_ID, () => owner.claimEmailAddress()), {
    address: "maya@noclick.email", paused: false, fromAnyone: true,
  });
  assert.equal(claim.last.headers.get("NoClick-User"), null); // the owner's address is the account's, never a user's
  api.on("POST", "/v1/humans/owner/reach/email", json({ object: "owner_email_address", address: null, paused: false, from_anyone: false }));
  assert.equal(await owner.claimEmailAddress(), null); // where NoClick takes no mail
  const rename = api.on("PATCH", "/v1/humans/owner/reach/email", json({
    object: "owner_email_address", address: "bakery-desk@noclick.email", paused: true, from_anyone: true,
  }));
  assert.deepEqual(await owner.renameEmailAddress("bakery-desk"), { address: "bakery-desk@noclick.email", paused: true, fromAnyone: true });
  assert.deepEqual(rename.last.body, { name: "bakery-desk" });
  api.on("PATCH", "/v1/humans/owner/reach/email", json(
    { error: { type: "conflict", message: "taken-name@noclick.email is taken; pick another name.", field: "name" } }, { status: 409 }));
  await assert.rejects(owner.renameEmailAddress("taken-name"), nc.Conflict);
  await assert.rejects(new nc.Human({ email: "ana@example.com" }).claimEmailAddress(), TypeError);
});

test("the owner adds an email by code", async () => {
  const { api } = setup();
  const sent = api.on("POST", "/v1/humans/owner/email", json({ object: "owner_email", status: "code_sent", email: "maya@morrowbakery.com" }));
  const owner = nc.Human.owner();
  await nc.asUser(USER_ID, () => owner.addEmail("maya@morrowbakery.com"));
  assert.deepEqual(sent.last.body, { email: "maya@morrowbakery.com" });
  assert.equal(sent.last.headers.get("NoClick-User"), null); // the owner's email is the account's, never a user's
  const confirm = api.on(
    "POST",
    "/v1/humans/owner/email/confirm",
    json({ object: "owner_email", status: "verified", email: "maya@morrowbakery.com", merged: false }),
  );
  assert.deepEqual(await owner.confirmEmail("482913"), { email: "maya@morrowbakery.com", status: "verified", merged: false });
  assert.deepEqual(confirm.last.body, { code: "482913" });
  await assert.rejects(new nc.Human({ email: "ana@example.com" }).addEmail("ana@example.com"), TypeError);
});

test("an inbox and a number take a conversation template", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/inboxes", json({ object: "inbox", id: "inb_1", address: "a@noclick.email", conversation: "owner" }));
  const inbox = await nc.Inbox.create({ localPart: "a", conversation: "owner" });
  assert.equal((create.last.body as Record<string, unknown>).conversation, "owner");
  assert.equal(inbox.conversation, "owner");
  const patch = api.on("PATCH", "/v1/inboxes/inb_1", json({ object: "inbox", id: "inb_1", address: "a@noclick.email", conversation: null }));
  await inbox.update({ conversation: null });
  assert.deepEqual(patch.last.body, { conversation: null });

  const answer = api.on("POST", "/v1/phone_numbers/pn_1/answer", json({ object: "phone_number", id: "pn_1" }));
  await nc.PhoneNumber.fromId("pn_1").answerWith(AGENT_ID, { conversation: "owner" });
  assert.deepEqual(answer.last.body, { agent_id: AGENT_ID, conversation: "owner" });
});
