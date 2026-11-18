import assert from "node:assert/strict";
import { test } from "node:test";

import { errorFromPayload } from "../src/errors.ts";
import * as nc from "../src/index.ts";
import { BASE, USER_ID, apiError, json, listing, setup, userRow } from "./helpers.ts";

test("auth and user-agent headers; reads carry no idempotency key", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/users", json(listing()));
  await nc.User.list();
  assert.equal(route.last.headers.get("Authorization"), "Bearer nk_live_test");
  assert.match(route.last.headers.get("User-Agent") ?? "", /^noclick-typescript\//);
  assert.equal(route.last.headers.get("Idempotency-Key"), null);
});

test("a missing API key is Unauthenticated with a next step", async () => {
  const saved = process.env.NOCLICK_API_KEY;
  delete process.env.NOCLICK_API_KEY;
  try {
    const client = new nc.NoClick({ baseUrl: BASE });
    await assert.rejects(nc.User.list({ client }), (err: nc.Unauthenticated) => {
      assert.ok(err instanceof nc.Unauthenticated && err instanceof nc.NoClickError);
      // A deployed app is told it needs no key at all.
      assert.match(err.nextStep ?? "", /^Set NOCLICK_API_KEY .* A deployed app needs neither: .*NOCLICK_DEPLOYMENT_TOKEN\.$/);
      return true;
    });
  } finally {
    if (saved !== undefined) process.env.NOCLICK_API_KEY = saved;
  }
});

/** Run `fn` as code in a runtime that looks like `globals` says (a Worker's `navigator`, a page's `document`). */
async function asIfIn(globals: Record<string, unknown>, fn: () => Promise<void>): Promise<void> {
  const saved = Object.keys(globals).map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)] as const);
  for (const [name, value] of Object.entries(globals)) {
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  }
  try {
    await fn();
  } finally {
    for (const [name, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete (globalThis as Record<string, unknown>)[name];
    }
  }
}

function nextStepOf(call: () => unknown): string {
  try {
    call();
  } catch (err) {
    assert.ok(err instanceof nc.Unauthenticated);
    return err.nextStep ?? "";
  }
  assert.fail("expected Unauthenticated");
}

test("a missing credential names the fix where the code runs", async () => {
  const saved = process.env.NOCLICK_API_KEY;
  delete process.env.NOCLICK_API_KEY;
  const client = new nc.NoClick({ baseUrl: BASE });
  try {
    // A Worker whose process.env isn't filled (no nodejs_compat): pass it from the handler's env.
    await asIfIn({ navigator: { userAgent: "Cloudflare-Workers" } }, async () => {
      await assert.rejects(nc.User.list({ client }), (err: nc.Unauthenticated) =>
        /nodejs_compat/.test(err.nextStep ?? "") && (err.nextStep ?? "").includes("configure({ apiKey: env.NOCLICK_API_KEY })"));
      assert.ok(nextStepOf(() => nc.Project.current()).includes(
        "Project.current({ client: new NoClick({ apiKey: env.NOCLICK_DEPLOYMENT_TOKEN }) })"));
    });
    // A page never holds a secret key: it signs in with its user's session.
    await asIfIn({ document: {} }, async () => {
      await assert.rejects(nc.AI.chat("hi", { client }), (err: nc.Unauthenticated) => /NoClick\.forSession/.test(err.nextStep ?? ""));
    });
    assert.match(nextStepOf(() => nc.Project.current()), /^Outside a deployment, use Project\.fromName/);
  } finally {
    if (saved !== undefined) process.env.NOCLICK_API_KEY = saved;
  }
});

test("inside a deployed app the whole client acts as the app, with no key", async () => {
  // NoClick puts the deployment's credential in its environment: the static calls (AI, Connection,
  // Channel, ...) and Project.current() sign in with it, through one client.
  const { api } = setup();
  const done = { id: "gen_1", choices: [{ index: 0, delta: { content: "Hi." }, finish_reason: "stop" }] };
  const chat = api.on("POST", "/v1/ai/chat/completions", () =>
    new Response(`data: ${JSON.stringify(done)}\n\ndata: [DONE]\n\n`, { headers: { "content-type": "text/event-stream" } }));
  const saved = process.env.NOCLICK_API_KEY;
  delete process.env.NOCLICK_API_KEY;
  process.env.NOCLICK_DEPLOYMENT_TOKEN = "nk_dep_123";
  try {
    const app = nc.configure({ baseUrl: BASE, fetch: api.fetch });
    assert.equal((await nc.AI.chat("Say hi")).text, "Hi.");
    assert.equal(chat.last.headers.get("Authorization"), "Bearer nk_dep_123");
    assert.equal(nc.Project.current()._client, app);
    // A key set beside it is what the static calls use; the app itself still acts as the app.
    process.env.NOCLICK_API_KEY = "nk_live_env";
    const keyed = nc.configure({ baseUrl: BASE, fetch: api.fetch });
    assert.equal(keyed.apiKey, "nk_live_env");
    const current = nc.Project.current()._client!;
    assert.ok(current !== keyed && current.inApp && current.apiKey === "nk_dep_123");
  } finally {
    delete process.env.NOCLICK_DEPLOYMENT_TOKEN;
    if (saved === undefined) delete process.env.NOCLICK_API_KEY;
    else process.env.NOCLICK_API_KEY = saved;
  }
});

test("configuration comes from the environment when options are absent", () => {
  const saved = { key: process.env.NOCLICK_API_KEY, url: process.env.NOCLICK_API_URL };
  process.env.NOCLICK_API_KEY = "nk_live_env";
  process.env.NOCLICK_API_URL = "https://example.test/";
  try {
    const client = new nc.NoClick();
    assert.equal(client.apiKey, "nk_live_env");
    assert.equal(client.baseUrl, "https://example.test");
    delete process.env.NOCLICK_API_URL;
    assert.equal(new nc.NoClick().baseUrl, "https://api.noclick.com");
    assert.equal(new nc.NoClick({ apiKey: "nk_live_opt" }).apiKey, "nk_live_opt");
  } finally {
    for (const [name, value] of [["NOCLICK_API_KEY", saved.key], ["NOCLICK_API_URL", saved.url]] as const) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});

test("write retries reuse one idempotency key; the next write gets a fresh one", async () => {
  const { api, sleeps } = setup();
  const route = api.on(
    "POST", "/v1/users",
    apiError(503, "server_error", "busy"),
    new Response("bad gateway", { status: 502 }),
    json(userRow()),
  );
  const user = await nc.User.create("user_42");
  assert.equal(user.id, USER_ID);
  const keys = new Set(route.calls.map((c) => c.headers.get("Idempotency-Key")));
  assert.equal(route.count, 3);
  assert.equal(keys.size, 1);
  assert.match([...keys][0] ?? "", /^nc_[0-9a-f]{32}$/);
  assert.equal(sleeps.length, 2);

  const second = api.on("POST", "/v1/users", json(userRow()));
  await nc.User.create("user_43");
  assert.ok(!keys.has(second.last.headers.get("Idempotency-Key")));
});

test("an explicit idempotency key is sent", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/users", json(userRow()));
  await nc.User.create("user_42", { idempotencyKey: "signup-42" });
  assert.equal(route.last.headers.get("Idempotency-Key"), "signup-42");
});

test("Retry-After is honoured (seconds)", async () => {
  const { api, sleeps } = setup();
  api.on("GET", "/v1/users", apiError(429, "rate_limited", "slow", {}, { "Retry-After": "7" }), json(listing()));
  assert.deepEqual(await nc.User.list(), []);
  assert.deepEqual(sleeps, [7000]);
});

test("exhausted rate limiting raises RateLimited carrying retryAfter", async () => {
  const { api, sleeps, client } = setup();
  api.on("GET", "/v1/users", apiError(429, "rate_limited", "slow down", {}, { "Retry-After": "2" }));
  await assert.rejects(nc.User.list(), (err: nc.RateLimited) => {
    assert.ok(err instanceof nc.RateLimited);
    assert.equal(err.retryAfter, 2);
    assert.equal(err.status, 429);
    return true;
  });
  assert.equal(sleeps.length, client.maxRetries);
});

test("quota_exceeded is never retried", async () => {
  const { api, sleeps } = setup();
  const route = api.on("POST", "/v1/users", apiError(429, "quota_exceeded", "monthly quota spent"));
  await assert.rejects(nc.User.create("user_42"), nc.QuotaExceeded);
  assert.equal(route.count, 1);
  assert.equal(sleeps.length, 0);
});

test("network errors retry with the same key, then succeed", async () => {
  const { api, sleeps, client } = setup();
  const route = api.on("POST", "/v1/users", new TypeError("fetch failed"), json(userRow()));
  await nc.User.create("user_42");
  assert.equal(route.count, 2);
  assert.equal(new Set(route.calls.map((c) => c.headers.get("Idempotency-Key"))).size, 1);
  assert.equal(sleeps.length, 1);
  assert.ok(sleeps[0] > 0 && sleeps[0] <= client.backoffMs);
});

test("Cloudflare's 52x are retried, a write with its one key", async () => {
  // Cloudflare's own answers when it couldn't get the API's (an unknown error, the origin down or timing out).
  const { api } = setup();
  const route = api.on("POST", "/v1/users", new Response(null, { status: 520 }),
    new Response("error code: 524", { status: 524 }), json(userRow()));
  await nc.User.create("user_42");
  assert.equal(route.count, 3);
  assert.equal(new Set(route.calls.map((c) => c.headers.get("Idempotency-Key"))).size, 1);
});

test("an error the API never answered names its request at the edge", async () => {
  const { api, sleeps, client } = setup();
  api.on("GET", "/v1/users", new Response(null, { status: 520, headers: { "cf-ray": "8f0a11bb22cc33dd-IAD" } }));
  await assert.rejects(nc.User.list(), (err: nc.ServerError) => {
    assert.ok(err instanceof nc.ServerError);
    assert.deepEqual([err.status, err.requestId, err.details.cf_ray], [520, "8f0a11bb22cc33dd-IAD", "8f0a11bb22cc33dd-IAD"]);
    assert.equal(err.message, "HTTP 520 from GET /v1/users (request 8f0a11bb22cc33dd-IAD)");
    return true;
  });
  assert.equal(sleeps.length, client.maxRetries);
  // The API's own id stays the request's, and the edge's is beside it.
  api.on("POST", "/v1/users", apiError(400, "invalid_request", "bad", {}, { "x-request-id": "req_1", "cf-ray": "8f0a11bb22cc33ee-IAD" }));
  await assert.rejects(nc.User.create("user_42"), (err: nc.InvalidRequest) => {
    assert.deepEqual([err.requestId, err.details.cf_ray, err.message], ["req_1", "8f0a11bb22cc33ee-IAD", "bad"]);
    return true;
  });
});

test("exhausted network errors raise APIConnectionError", async () => {
  const { api } = setup();
  api.on("GET", "/v1/users", new TypeError("fetch failed"));
  await assert.rejects(nc.User.list(), nc.APIConnectionError);
});

test("a caller's abort signal stops the request without retries", async () => {
  const { api, client } = setup();
  const controller = new AbortController();
  const route = api.on("GET", "/v1/users", () => {
    controller.abort();
    throw new DOMException("aborted", "AbortError");
  });
  await assert.rejects(client.request("GET", "/v1/users", { signal: controller.signal }), { name: "AbortError" });
  assert.equal(route.count, 1);
});

test("a POST's 500 is not retried (the server replays it); a read's is", async () => {
  const { api, sleeps } = setup();
  const unknown = apiError(500, "internal_error", "some of its work may have happened");
  const write = api.on("POST", "/v1/users", unknown);
  await assert.rejects(nc.User.create("user_42"), (err: nc.NoClickError) => err.status === 500);
  assert.equal(write.count, 1);
  assert.equal(sleeps.length, 0);
  const read = api.on("GET", "/v1/users", unknown, json(listing()));
  assert.deepEqual(await nc.User.list(), []);
  assert.equal(read.count, 2);
});

test("a browser sends no User-Agent (the browser owns it)", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/users", json(listing()));
  const scope = globalThis as { document?: unknown };
  scope.document = {};
  try {
    await nc.User.list();
  } finally {
    delete scope.document;
  }
  assert.equal(route.last.headers.get("User-Agent"), null);
  assert.equal(route.last.headers.get("Authorization"), "Bearer nk_live_test");
});

test("a refused run is UpstreamError in the service's words at once; a failed service's is retried", async () => {
  // A refusal answers 424, which the edge passes through and nothing retries: as a 502 it was retried
  // for minutes, until a bare ServerError carrying the edge's page came back.
  const { api, sleeps } = setup();
  const refused = api.on("POST", "/v1/run", apiError(424, "upstream_error", "Stripe refused stripe.list_charges (401): Invalid API Key provided.", {
    next_step: "Fix what the provider objected to, then retry.", upstream_status: 401, integration: "stripe", operation: "list_charges",
  }));
  await assert.rejects(nc.run("stripe.list_charges", { limit: 3 }), (err: nc.NoClickError) =>
    err instanceof nc.UpstreamError && err.status === 424 && err.details.upstream_status === 401 && err.message.includes("Invalid API Key"));
  assert.equal(refused.count, 1);
  assert.equal(sleeps.length, 0);

  // A failure answers 503, which the edge passes through whole; the type decides the class whatever the status.
  for (const status of [503, 502]) {
    const failed = api.on("POST", "/v1/run", apiError(status, "upstream_error", "Exa is unavailable right now."));
    await assert.rejects(nc.run("exa.search", { query: "x" }), (err: nc.NoClickError) => err instanceof nc.UpstreamError && err.status === status);
    assert.equal(failed.count, 3);
  }
});

test("a replayed answer isn't retried, and an error says how often the call was sent and whether it took effect", async () => {
  // The server kept the first answer because the write may have happened there: sending it again gets it again.
  const { api } = setup();
  const unknown = ["The database is unavailable right now (NoClick tried 3 times), and NoClick can't tell whether the call took effect.",
    { upstream_attempts: 3 }] as const;
  const route = api.on("POST", "/v1/users", apiError(503, "upstream_error", ...unknown),
    apiError(503, "upstream_error", ...unknown, { "Idempotent-Replayed": "true" }));
  await assert.rejects(nc.User.create("user_42"), (err: nc.UpstreamError) => {
    assert.ok(err instanceof nc.UpstreamError);
    assert.deepEqual([err.attempts, err.upstreamAttempts, err.applied], [2, 3, null]);
    assert.equal(err.toJSON().attempts, 2);
    return true;
  });
  assert.equal(route.count, 2);
  const nothing = errorFromPayload({ error: { type: "upstream_error", message: "m", applied: false } }) as nc.UpstreamError;
  assert.deepEqual([nothing.applied, nothing.upstreamAttempts, nothing.attempts], [false, undefined, null]);
});

test("a timeout is RequestTimeout naming its operation, never retried, whatever its status", async () => {
  const { api, sleeps } = setup();
  for (const status of [503, 504]) {
    const late = api.on("POST", "/v1/run", apiError(status, "request_timeout", "The run is still going after 90 seconds.", {
      next_step: "Wait on the operation.", operation_id: "op_1", conversation: "c1",
    }));
    await assert.rejects(nc.run("exa.search", { query: "x" }), (err: nc.NoClickError) =>
      err instanceof nc.RequestTimeout && err.status === status && err.details.operation_id === "op_1" && err.details.conversation === "c1");
    assert.equal(late.count, 1);
  }
  assert.equal(sleeps.length, 0);
});

test("client errors are not retried", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/users", apiError(400, "invalid_request", "bad"));
  await assert.rejects(nc.User.create("user_42"), nc.InvalidRequest);
  assert.equal(route.count, 1);
});

test("an explicit client is used instead of the default", async () => {
  const { api } = setup();
  const other = new nc.NoClick({ apiKey: "nk_live_other", baseUrl: BASE, fetch: api.fetch });
  const route = api.on("GET", "/v1/users", json(listing()));
  await nc.User.list({ client: other });
  assert.equal(route.last.headers.get("Authorization"), "Bearer nk_live_other");
});

test("listings follow next_cursor", async () => {
  const { api } = setup();
  const route = api.on(
    "GET", "/v1/users",
    json(listing([userRow({ id: "a" })], "c2")),
    json(listing([userRow({ id: "b" })])),
  );
  const users = await nc.User.list();
  assert.deepEqual(users.map((u) => u.id), ["a", "b"]);
  assert.equal(route.calls[1].query.get("cursor"), "c2");
});

test("the JSON body is compact and snake_case", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/users", json(userRow()));
  await nc.User.create("user_42", { email: "ana@example.com", spendCapUsdPerMonth: 5, name: null });
  assert.deepEqual(route.last.body, { id: "user_42", email: "ana@example.com", spend_cap_usd_per_month: 5 });
  assert.equal(route.last.headers.get("Content-Type"), "application/json");
});

test("an HTML error page becomes a typed error with the status in the message", async () => {
  const { api } = setup();
  api.on("GET", "/v1/users", new Response("<h1>Forbidden</h1>", { status: 403 }));
  await assert.rejects(nc.User.list(), (err: nc.PermissionDenied) => {
    assert.ok(err instanceof nc.PermissionDenied);
    assert.match(err.message, /HTTP 403 from GET \/v1\/users: <h1>Forbidden/);
    return true;
  });
});
