// Which of the app's popups your account's owner sees (`Popups`), and the numbers linked to your account
// (`AccountPhones`): both the account's, never a user's, so neither sends `NoClick-User` inside `asUser`.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const POPUPS = { run_results: true, invite_banner: false, publish_banner: true };

test("Popups.get reads whether each popup shows, as the account", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/popups", json({ object: "popups", popups: POPUPS }));
  const { popups } = await nc.asUser("user_42", () => nc.Popups.get());
  assert.deepEqual(popups, POPUPS);
  assert.equal(read.last.headers.get("NoClick-User"), null);
});

test("Popups.update sends only the popups it names", async () => {
  const { api } = setup();
  const patch = api.on("PATCH", "/v1/popups", json({ object: "popups", popups: { ...POPUPS, invite_banner: true } }));
  const { popups } = await nc.Popups.update({ invite_banner: true });
  assert.deepEqual(patch.last.body, { popups: { invite_banner: true } });
  assert.equal(patch.last.headers.get("NoClick-User"), null);
  assert.equal(popups.invite_banner, true);
});

test("a popup the app doesn't have rejects with InvalidRequest", async () => {
  const { api } = setup();
  api.on("PATCH", "/v1/popups", apiError(400, "invalid_request", "popups.tour: not a popup"));
  await assert.rejects(nc.Popups.update({ tour: false }), nc.InvalidRequest);
});

const PHONES = {
  object: "phones", configured: true, max_phones: 5,
  phones: [
    { phone: "+14155550123", verified_at: "2026-10-02T09:00:00+00:00", source: "verify" },
    { phone: "+447700900123", verified_at: "2026-11-11T09:00:00+00:00", source: "whatsapp" },
  ],
};

test("AccountPhones.get reads the linked numbers, as the account", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/account/phones", json(PHONES));
  const linked = await nc.asUser("user_42", () => nc.AccountPhones.get());
  assert.deepEqual([linked.configured, linked.maxPhones], [true, 5]);
  assert.deepEqual(linked.phones.map((p) => [p.phone, p.source, p.verifiedAt?.toISOString()]), [
    ["+14155550123", "verify", "2026-10-02T09:00:00.000Z"],
    ["+447700900123", "whatsapp", "2026-11-11T09:00:00.000Z"],
  ]);
  assert.equal(read.last.headers.get("NoClick-User"), null);
});

test("AccountPhones.link texts a code and verify links the number", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/account/phones", json({
    object: "phone_challenge", id: "ch_1", phone: "+14155550123", expires_at: "2026-11-21T12:10:00+00:00",
  }, { status: 201 }));
  const check = api.on("POST", "/v1/account/phones/verify", json({
    object: "phone", phone: "+14155550123", verified_at: "2026-11-21T12:01:00+00:00", source: "verify",
  }));
  const challenge = await nc.AccountPhones.link("+1 415 555 0123");
  assert.deepEqual(start.last.body, { phone: "+1 415 555 0123" });
  assert.deepEqual([challenge.id, challenge.phone, challenge.expiresAt?.toISOString()], ["ch_1", "+14155550123", "2026-11-21T12:10:00.000Z"]);
  const phone = await nc.AccountPhones.verify(challenge.id, "123456");
  assert.deepEqual(check.last.body, { challenge_id: "ch_1", code: "123456" });
  assert.deepEqual([phone.phone, phone.source], ["+14155550123", "verify"]);
});

test("a wrong code rejects with InvalidRequest naming why", async () => {
  const { api } = setup();
  api.on("POST", "/v1/account/phones/verify", apiError(400, "invalid_request", "That code isn't right", { reason: "invalid_code" }));
  const refused = await nc.AccountPhones.verify("ch_1", "000000").catch((error: unknown) => error);
  assert.ok(refused instanceof nc.InvalidRequest);
  assert.equal(refused.details.reason, "invalid_code");
});

test("AccountPhones.unlink names the number in the path", async () => {
  const { api } = setup();
  const removed = api.on("DELETE", "/v1/account/phones/%2B14155550123", json({ object: "phone", phone: "+14155550123", unlinked: true }));
  await nc.AccountPhones.unlink("+14155550123");
  assert.equal(removed.calls.length, 1);
});

test("a key without account:phones rejects with PermissionDenied", async () => {
  const { api } = setup();
  api.on("GET", "/v1/account/phones", apiError(403, "permission_denied", "This key lacks the 'account:phones' scope"));
  await assert.rejects(nc.AccountPhones.get(), nc.PermissionDenied);
});

test("Popups.seenOnce and setSeenOnce read and mark the owner's show-once flags, as the account", async () => {
  const { api } = setup();
  const read = api.on("GET", "/v1/popups/seen", json({ object: "seen_once", seen_once: { invite_walkthrough: true } }));
  const marked = api.on("PATCH", "/v1/popups/seen", json({ object: "seen_once", seen_once: { invite_walkthrough: true, quickpublish_walkthrough: true } }));
  assert.deepEqual(await nc.asUser("user_42", () => nc.Popups.seenOnce()), { invite_walkthrough: true });
  const seen = await nc.Popups.setSeenOnce({ quickpublish_walkthrough: true });
  assert.deepEqual(marked.last.body, { seen_once: { quickpublish_walkthrough: true } });
  assert.deepEqual(seen, { invite_walkthrough: true, quickpublish_walkthrough: true });
  assert.equal(read.last.headers.get("NoClick-User"), null);
});

test("AccountPhones.linkCode mints the account's code", async () => {
  const { api } = setup();
  const minted = api.on("POST", "/v1/account/phones/link_code", json({ object: "phone_link_code", code: "NC-7Q4M", expires_in: 540 }));
  assert.deepEqual(await nc.asUser("user_42", () => nc.AccountPhones.linkCode()), { code: "NC-7Q4M", expiresIn: 540 });
  assert.equal(minted.last.headers.get("NoClick-User"), null);
});
