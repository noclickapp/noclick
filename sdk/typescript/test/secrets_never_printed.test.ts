// Errors, clients and the objects holding one never print or serialize the client's key.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
import { format, inspect } from "node:util";

import * as nc from "../src/index.ts";
import { BASE, MockApi, json } from "./helpers.ts";

const KEY = "nk_live_FAKEKEY4c9e2f7a";
const HEADER_SECRET = "hdr_FAKE8d1b3e";
const OFFER = { kind: "funds", label: "$10 of funds", price_usd: 10, url: "https://noclick.com/pay/j_1", operation_id: "op_pay" };
const CASES = [
  { status: 402, cls: nc.PaymentRequired, body: { error: { type: "payment_required", message: "Your account can't pay for this.", offers: [OFFER] } } },
  { status: 500, cls: nc.ServerError, body: { error: { type: "internal_error", message: "Something broke." } } },
] as const;

function client(api: MockApi): nc.NoClick {
  const made = new nc.NoClick({ apiKey: KEY, baseUrl: BASE, fetch: api.fetch, headers: { "X-Proxy-Token": HEADER_SECRET } });
  made._sleep = async () => {};
  return made;
}

function printed(value: unknown): string[] {
  return [
    inspect(value, { showHidden: true, depth: null }),
    inspect(value, { showHidden: true, depth: null, getters: true }),
    format("%o", value),
    format("%O", value),
    JSON.stringify(value) ?? "",
    String(value),
    value instanceof Error ? (value.stack ?? "") : "",
  ];
}

function assertNoSecret(texts: string[], what: string): void {
  for (const text of texts) {
    assert.ok(!text.includes(KEY), `${what} printed the key:\n${text}`);
    assert.ok(!text.includes(HEADER_SECRET), `${what} printed a header:\n${text}`);
  }
}

for (const { status, cls, body } of CASES) {
  test(`a ${status} error prints and serializes without the key, and its follow-ups still use it`, async () => {
    const api = new MockApi();
    const route = api.on("GET", "/v1/users/user_42", json(body, { status }));
    const wait = api.on("GET", "/v1/operations/op_pay/wait", json({ object: "operation", id: "op_pay", kind: "payment", status: "succeeded", result: {} }));
    const err = await nc.User.get("user_42", { client: client(api) }).catch((e: unknown) => e);
    assert.ok(err instanceof cls);
    assert.equal(route.last.headers.get("Authorization"), `Bearer ${KEY}`);
    if (err instanceof nc.PaymentRequired) {
      // Read first, so the error holds operations that hold the client.
      assert.equal(err.offers[0].operation.id, "op_pay");
      await err.offers[0].operation.wait();
      assert.equal(wait.last.headers.get("Authorization"), `Bearer ${KEY}`);
    } else {
      assert.equal(route.count, 4); // retried: a read's 500
    }
    assertNoSecret(printed(err), cls.name);
  });

  test(`an uncaught ${status} error's output carries no key`, () => {
    const script = `
      import { NoClick, User } from ${JSON.stringify(pathToFileURL(new URL("../src/index.ts", import.meta.url).pathname).href)};
      const client = new NoClick({
        apiKey: process.env.NC_KEY, baseUrl: "https://api.test", maxRetries: 0, headers: { "X-Proxy-Token": process.env.NC_HEADER },
        fetch: async () => new Response(process.env.NC_BODY, { status: Number(process.env.NC_STATUS), headers: { "content-type": "application/json" } }),
      });
      const err = await User.get("user_42", { client }).catch((e) => e);
      if ("offers" in err) void err.offers;
      throw err;
    `;
    const run = spawnSync(process.execPath, ["--experimental-strip-types", "--disable-warning=ExperimentalWarning", "--input-type=module", "-e", script], {
      encoding: "utf8",
      env: { ...process.env, NC_KEY: KEY, NC_HEADER: HEADER_SECRET, NC_BODY: JSON.stringify(body), NC_STATUS: String(status) },
    });
    assert.notEqual(run.status, 0);
    // Node printed the error with its properties, so this checks the dump, not an empty stream.
    assert.match(run.stderr, new RegExp(`${cls.name}: .*\\n[\\s\\S]*type: '${body.error.type}'`));
    assertNoSecret([run.stderr, run.stdout], "the uncaught error");
  });
}

test("a client, and anything holding one, prints and serializes without its key", () => {
  const made = client(new MockApi());
  assert.equal(made.apiKey, KEY);
  const operation = nc.Operation.fromId("op_1", { client: made });
  for (const value of [made, operation, { ...made }, Object.values(made)]) assertNoSecret(printed(value), "a client");
  assertNoSecret([inspect(made, { customInspect: false, showHidden: true, depth: null })], "a client");
  assert.equal(inspect(made), `NoClick { baseUrl: "${BASE}" }`);
});
