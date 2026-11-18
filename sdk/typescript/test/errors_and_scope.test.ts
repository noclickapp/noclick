import assert from "node:assert/strict";
import { test } from "node:test";

import { errorFromPayload } from "../src/errors.ts";
import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, setup, userRow } from "./helpers.ts";
import type { Call } from "./helpers.ts";

// --- errors ------------------------------------------------------------------

test("every server type maps to its class, status and fields", () => {
  const cases: [string, number, typeof nc.NoClickError][] = [
    ["invalid_request", 400, nc.InvalidRequest], ["unauthenticated", 401, nc.Unauthenticated],
    ["payment_required", 402, nc.PaymentRequired], ["plan_required", 402, nc.PlanRequired],
    ["price_exceeded", 402, nc.PriceExceeded], ["approval_required", 402, nc.ApprovalRequired],
    ["spend_cap_exceeded", 402, nc.SpendCapExceeded], ["spending_paused", 402, nc.SpendingPaused],
    ["permission_denied", 403, nc.PermissionDenied],
    ["policy_denied", 403, nc.PolicyDenied], ["not_found", 404, nc.NotFound], ["conflict", 409, nc.Conflict],
    ["not_available", 409, nc.NotAvailable], ["action_required", 409, nc.ActionRequired], ["expired", 410, nc.Expired],
    ["needs_connection", 424, nc.NeedsConnection], ["credential_disconnected", 424, nc.CredentialDisconnected],
    ["quota_exceeded", 429, nc.QuotaExceeded], ["rate_limited", 429, nc.RateLimited],
    ["upstream_error", 503, nc.UpstreamError], ["request_timeout", 503, nc.RequestTimeout],
  ];
  for (const [type, status, cls] of cases) {
    const err = errorFromPayload({ error: { type, message: "m", next_step: "do x", extra: 1 } }, { status, requestId: "r1" });
    assert.ok(err instanceof cls && err instanceof nc.NoClickError && err instanceof Error, type);
    assert.equal(err.type, type);
    assert.equal(err.status, status);
    assert.equal(err.nextStep, "do x");
    assert.equal(err.requestId, "r1");
    assert.deepEqual(err.details, { extra: 1 });
    assert.equal(err.name, cls.name);
    assert.equal(cls.httpStatus, status, type);
  }
});

test("PaymentRequired says, in dollars, what's left and what's needed", () => {
  const err = errorFromPayload({ error: {
    type: "payment_required", message: "Your account can't pay for this: $0.12 left, $0.50 needed. Add funds in the console.",
    next_step: "Add funds at https://noclick.com/dashboard?action=topup, then retry.", balance_usd: 0.12, required_usd: 0.5,
  } }, { status: 402 });
  assert.ok(err instanceof nc.PaymentRequired);
  assert.equal(err.balanceUsd, 0.12);
  assert.equal(err.requiredUsd, 0.5);
});

test("OpenAI's envelope (/v1/ai) maps by code, the platform's type", () => {
  const err = errorFromPayload(
    { error: { message: "m", type: "insufficient_quota", code: "spend_cap_exceeded", param: null, scope: "key" } }, { status: 402 });
  assert.ok(err instanceof nc.SpendCapExceeded);
  assert.equal(err.type, "spend_cap_exceeded");
  assert.deepEqual(err.details, { code: "spend_cap_exceeded", param: null, scope: "key" });
});

test("typed detail getters", () => {
  const needs = errorFromPayload({ type: "needs_connection", message: "m", integration: "gmail", connect_url: "https://c/1" });
  assert.ok(needs instanceof nc.NeedsConnection);
  assert.equal(needs.connectUrl, "https://c/1");
  assert.equal(needs.integration, "gmail");

  const conflict = errorFromPayload({ type: "conflict", message: "m", existing_id: "t_1" }) as nc.Conflict;
  assert.equal(conflict.existingId, "t_1");

  const cap = errorFromPayload({ type: "spend_cap_exceeded", message: "m", cap: 10, spent: 10.5, scope: "user" }) as nc.SpendCapExceeded;
  assert.deepEqual([cap.cap, cap.spent, cap.scope, cap.status], [10, 10.5, "user", 402]);

  const approval = errorFromPayload({
    type: "approval_required", message: "m", approval_id: "ap_1", request_id: "hr_1", approve_url: "https://h/1",
    operation: { object: "operation", id: "op_9", kind: "human.approve" },
  }) as nc.ApprovalRequired;
  assert.deepEqual([approval.approvalId, approval.approveUrl, approval.operationId], ["ap_1", "https://h/1", "op_9"]);
  // A policy's approval is the request a person answers.
  const request = approval.operation;
  assert.ok(request instanceof nc.HumanRequest);
  assert.deepEqual([request.requestId, request.url], ["hr_1", "https://h/1"]);
});

/** What the gate answers for a call it holds for the account's owner: the held call's id, never a request's. */
const HELD_FOR_THE_OWNER = {
  status: "awaiting_approval", approval_id: "ap_h", operation_id: "op_held", summary: "Send an email from 'gmail'",
  price: null, expires_at: "2026-10-31T10:00:00Z", accepting: null, sent_to: ["email"],
  next_step: "Tell them to tap the link NoClick sent them; it runs once they approve.",
};

test("a call held for the owner waits on the held call itself", async () => {
  const { api } = setup();
  const run = api.on("POST", "/v1/connections/gmail/operations/send_email/run",
    apiError(402, "approval_required", "Send an email from 'gmail': it waits for the account's owner.", HELD_FOR_THE_OWNER));
  const wait = api.on("GET", "/v1/operations/op_held/wait", json({
    object: "operation", id: "op_held", kind: "gate.held_call", status: "succeeded", error: null,
    result: { status: 200, response: { object: "operation_result", result: { id: "msg_1" } } },
  }));
  let held: nc.ApprovalRequired | undefined;
  await nc.asUser("user_42", async () => {
    await assert.rejects(nc.Connection.fromName("gmail").run("send_email", { to: "a@b.c" }), (err: unknown) => {
      held = err as nc.ApprovalRequired;
      return err instanceof nc.ApprovalRequired;
    });
  });
  assert.deepEqual([held?.approvalId, held?.operationId, held?.details.sent_to], ["ap_h", "op_held", ["email"]]);
  const call = held?.operation;
  assert.ok(call instanceof nc.Operation && !(call instanceof nc.HumanRequest));
  assert.equal(held?.operation, call); // cached
  assert.deepEqual([call.id, call.kind], ["op_held", "gate.held_call"]);
  // NoClick makes the call once the owner approves: its answer is the held call's result, nothing is retried.
  assert.deepEqual(await call.wait(), { status: 200, response: { object: "operation_result", result: { id: "msg_1" } } });
  assert.equal(wait.last.headers.get("NoClick-User"), "user_42");
  assert.equal(run.count, 1);
});

test("a held call the owner declines throws from its wait", async () => {
  const { api } = setup();
  api.on("POST", "/v1/connections/gmail/operations/send_email/run",
    apiError(402, "approval_required", "It waits for the account's owner.", HELD_FOR_THE_OWNER));
  api.on("GET", "/v1/operations/op_held/wait", json({
    object: "operation", id: "op_held", kind: "gate.held_call", status: "failed", result: null,
    error: { type: "policy_denied", message: "The person declined it." },
  }));
  const err = await nc.Connection.fromName("gmail").run("send_email", { to: "a@b.c" }).catch((e: unknown) => e);
  assert.ok(err instanceof nc.ApprovalRequired);
  await assert.rejects(err.operation!.wait(), (e: unknown) => e instanceof nc.PolicyDenied && /declined/.test(e.message));
});

test("unknown types fall back by status and stay visible", () => {
  const byStatus = errorFromPayload({ error: { type: "brand_new", message: "m" } }, { status: 404 });
  assert.ok(byStatus instanceof nc.NotFound);
  assert.equal(byStatus.type, "brand_new");
  const server = errorFromPayload({ error: { type: "weird", message: "m" } }, { status: 502 });
  assert.ok(server instanceof nc.ServerError);
  const bare = errorFromPayload("boom", { status: 418 });
  assert.equal(bare.constructor, nc.NoClickError);
  assert.equal(bare.message, "boom");
});

test("toString carries the next step; OperationExpired is Expired", () => {
  const err = new nc.PolicyDenied("gmail.send_email is denied.", { nextStep: "Ask an admin." });
  assert.equal(String(err), "PolicyDenied: gmail.send_email is denied. Next step: Ask an admin.");
  assert.equal(nc.OperationExpired, nc.Expired);
});

test("errors from a real call carry the request id and details", async () => {
  const { api } = setup();
  api.on("POST", "/v1/connections/gmail/operations/send_email/run", json(
    { error: { type: "needs_connection", message: "Connect Gmail first.", next_step: "Open the link.", connect_url: "https://c/9", integration: "gmail" } },
    { status: 424, headers: { "x-request-id": "req_7" } },
  ));
  await assert.rejects(nc.Connection.fromName("gmail").run("send_email", { to: "a@b.c" }), (err: nc.NeedsConnection) => {
    assert.ok(err instanceof nc.NeedsConnection);
    assert.equal(err.connectUrl, "https://c/9");
    assert.equal(err.requestId, "req_7");
    assert.equal(err.nextStep, "Open the link.");
    return true;
  });
});

// --- acting as a user -------------------------------------------------------

function header(route: { last: { headers: Headers } }): string | null {
  return route.last.headers.get("NoClick-User");
}

test("an approval the owner answers for a user's call is waited on as the account", async () => {
  const { api } = setup();
  api.on("POST", "/v1/connections/gmail/operations/send_email/run", json({ error: {
    type: "approval_required", message: "Needs the owner's approval.", next_step: "Wait, then retry.",
    approval_id: "ap_7", approver: "owner",
    operation: { object: "operation", id: "op_own", kind: "human.approve", status: "awaiting_human", user_id: null },
  } }, { status: 402 }));
  const wait = api.on("GET", "/v1/operations/op_own/wait", json({
    object: "operation", id: "op_own", kind: "human.approve", status: "succeeded", result: { approved: true }, user_id: null,
  }));
  await nc.asUser("user_42", async () => {
    const err = await nc.Connection.fromName("gmail").run("send_email", { to: "a@b.c" }).then(
      () => assert.fail("the call was held"), (e: unknown) => e);
    assert.ok(err instanceof nc.ApprovalRequired);
    assert.equal(err.approveUrl, undefined);
    assert.equal(await err.operation?.wait(), true);
  });
  assert.equal(header(wait), null);
});

test("no user header by default", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/connections", json(listing()));
  await nc.Connection.list();
  assert.equal(header(route), null);
});

test("any string is your id for the user, sent as it is", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/connections", json(listing()));
  for (const id of ["user_42", "3f2c8f4e-9a51-4d0e-9d7a-1b2c3d4e5f60", "auth0|123", "external:acme", "ALL", "a", "x".repeat(255)]) {
    await nc.asUser(id, () => nc.Connection.list());
    assert.equal(header(route), id);
  }
});

test("an id that breaks a rule is refused before anything is sent, naming the rule", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/connections", json(listing()));
  const cases: [string, RegExp][] = [
    ["", /1 to 255 characters, not 0/],
    ["x".repeat(256), /1 to 255 characters, not 256/],
    ["ana silva", /printable ASCII without spaces/],
    ["user\t42", /printable ASCII without spaces/],
    ["jörg", /printable ASCII without spaces/],
    ["org/42", /can't contain "\/"/],
    ["all", /"all" is reserved for list filters/],
    ["none", /"none" is reserved for list filters/],
    [".", /"\." can't be a user id: URLs resolve it away/],
    ["..", /"\.\." can't be a user id: URLs resolve it away/],
  ];
  for (const [id, rule] of cases) {
    await assert.rejects(nc.asUser(id, () => nc.Connection.list()), (err: nc.InvalidRequest) => {
      assert.ok(err instanceof nc.InvalidRequest, JSON.stringify(id));
      assert.match(err.message, rule);
      assert.equal(err.details.field, "id");
      return true;
    });
    await assert.rejects(nc.Connection.list({ user: id }), nc.InvalidRequest);
    assert.throws(() => nc.User.fromId(id), nc.InvalidRequest);
    await assert.rejects(nc.User.create(id), nc.InvalidRequest);
  }
  assert.equal(route.count, 0);
});

test("asUser nests, restores, and null means the account", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/connections", json(listing()));
  await nc.asUser("a", async () => {
    await nc.asUser("b", async () => {
      await nc.Connection.list();
      assert.equal(header(route), "b");
    });
    await nc.Connection.list();
    assert.equal(header(route), "a");
    await nc.asUser(null, async () => {
      await nc.Connection.list();
      assert.equal(header(route), null);
    });
  });
  assert.equal(nc.currentUser(), null);
});

test("concurrent asUser scopes never leak into each other", async () => {
  const { api } = setup();
  const seen: [string, string | null][] = [];
  api.on("GET", "/v1/connections", async (call) => {
    await new Promise((resolve) => setTimeout(resolve, Math.random() * 5));
    seen.push([call.query.get("integration") ?? "", call.headers.get("NoClick-User")]);
    return json(listing());
  });
  await Promise.all(["u1", "u2", "u3", "u4"].map((user) =>
    nc.asUser(user, async () => {
      for (let i = 0; i < 3; i++) {
        await new Promise((resolve) => setTimeout(resolve, Math.random() * 3));
        await nc.Connection.list({ integration: user });
      }
    }),
  ));
  assert.equal(seen.length, 12);
  for (const [user, sent] of seen) assert.equal(sent, user);
});

test("an explicit user option wins over the ambient one", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/connections", json(listing()));
  await nc.asUser("a", async () => {
    await nc.Connection.list({ user: "b" });
    assert.equal(header(route), "b");
    await nc.Connection.list({ user: null });
    assert.equal(header(route), null);
  });
});

test("client.asUser is the same scope", async () => {
  const { api, client } = setup();
  const route = api.on("GET", "/v1/connections", json(listing()));
  const result = await client.asUser("user_9", async () => {
    await nc.Connection.list();
    return nc.currentUser();
  });
  assert.equal(result, "user_9");
  assert.equal(header(route), "user_9");
});

test("asUser with a hydrated User uses its id", async () => {
  const { api } = setup();
  api.on("GET", `/v1/users/${USER_ID}`, json(userRow()));
  const route = api.on("GET", "/v1/connections", json(listing()));
  const user = await nc.User.get(USER_ID);
  await nc.asUser(user, () => nc.Connection.list());
  assert.equal(header(route), USER_ID);
});

test("a lazy user without createIfMissing sends its id with no lookup", async () => {
  const { api } = setup();
  const lookup = api.on("GET", `/v1/users/${USER_ID}`, json(userRow()));
  const route = api.on("GET", "/v1/connections", json(listing()));
  await nc.asUser(nc.User.fromId(USER_ID), () => nc.Connection.list());
  assert.equal(header(route), USER_ID);
  assert.equal(lookup.count, 0);
});

test("a lazy user with createIfMissing is created once, before first use", async () => {
  const { api } = setup();
  const lookup = api.on("GET", `/v1/users/${USER_ID}`, apiError(404, "not_found", "No user has that id."));
  const create = api.on("POST", "/v1/users", json(userRow({ email: "ana@example.com" })));
  const route = api.on("GET", "/v1/connections", json(listing()));
  const user = nc.User.fromId(USER_ID, { createIfMissing: true, email: "ana@example.com" });
  assert.equal(user.isHydrated, false);
  assert.equal(create.count, 0);
  await nc.asUser(user, async () => {
    await nc.Connection.list();
    await nc.Connection.list();
  });
  assert.equal(header(route), USER_ID);
  assert.equal(lookup.count, 1);
  assert.equal(create.count, 1);
  assert.deepEqual(create.last.body, { id: USER_ID, email: "ana@example.com" });
  assert.equal(create.last.headers.get("NoClick-User"), null); // user routes never carry one
  assert.equal(lookup.last.headers.get("NoClick-User"), null);
});

test("a lazy user with createIfMissing that exists is adopted and converged to the definition", async () => {
  const { api } = setup();
  const lookup = api.on("GET", `/v1/users/${USER_ID}`, json(userRow({ name: "Ana", email: "old@example.com", phone: "+14155550100" })));
  const create = api.on("POST", "/v1/users", json(userRow()));
  const patch = api.on("PATCH", `/v1/users/${USER_ID}`, (call: Call) => json(userRow({ name: "Ana", ...(call.body as object) })));
  const user = await nc.User.fromId(USER_ID, {
    createIfMissing: true, name: "Ana", email: "ana@example.com", phone: null, metadata: { plan: "pro" },
  }).hydrate();
  // Only what differs is sent; null clears; a field left out (spend cap) is never touched.
  assert.deepEqual(patch.last.body, { email: "ana@example.com", phone: null, metadata: { plan: "pro" } });
  assert.equal(user.email, "ana@example.com");
  assert.equal(lookup.count, 1);
  assert.equal(create.count, 0);
  await nc.User.fromId(USER_ID, { createIfMissing: true, name: "Ana" }).hydrate();
  assert.equal(patch.count, 1);
});

test("a concurrent create is adopted through Conflict", async () => {
  const { api } = setup();
  const get = api.on("GET", `/v1/users/${USER_ID}`, apiError(404, "not_found", "No user has that id."), json(userRow()));
  api.on("POST", "/v1/users", apiError(409, "conflict", "exists", { existing_id: USER_ID }));
  const user = await nc.User.fromId(USER_ID, { createIfMissing: true }).hydrate();
  assert.equal(user.id, USER_ID);
  assert.equal(get.count, 2);
});

test("a missing user without createIfMissing is NotFound", async () => {
  const { api } = setup();
  api.on("GET", "/v1/users/nobody", apiError(404, "not_found", "No user has id \"nobody\"."));
  await assert.rejects(nc.User.get("nobody"), nc.NotFound);
});

test("ids go into paths percent-encoded", async () => {
  const { api } = setup();
  const get = api.on("GET", "/v1/users/auth0%7C123", json(userRow({ id: "auth0|123" })));
  const user = await nc.User.get("auth0|123");
  assert.equal(user.id, "auth0|123");
  assert.equal(get.count, 1);
  const suspend = api.on("POST", "/v1/users/a%3Fb%23c%25d/suspend", json(userRow({ id: "a?b#c%d", status: "suspended" })));
  await nc.User.fromId("a?b#c%d").suspend();
  assert.equal(suspend.count, 1);
});

test("asUser rejects other types", async () => {
  await assert.rejects(nc.asUser(42 as unknown as string, () => null), TypeError);
});

test("reading an unloaded field says how to load it", () => {
  const user = nc.User.fromId("user_42");
  assert.equal(user.id, "user_42");
  assert.throws(() => user.status, /hydrate\(\)/);
});
