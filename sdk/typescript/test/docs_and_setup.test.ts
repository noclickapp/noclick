// The calls a coding agent makes before it has a key, and the one that hands an app's change to its coding agent:
// the docs (searched and read with no key), a setup code redeemed for a key, and `app.live.change`.

import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, operation, setup } from "./helpers.ts";

test("Docs.search and Docs.read send no key", async () => {
  const { api } = setup();
  const searched = api.on("GET", "/v1/docs", json({ object: "list", data: [
    { id: "guide:apps", kind: "guide", title: "Apps", url: "https://noclick.com/docs/guide/apps", snippet: "Deploy…", status: "built" },
  ] }));
  const read = api.on("GET", "/v1/docs/skill:ship-an-app", json({
    object: "doc", id: "skill:ship-an-app", kind: "skill", title: "Ship an app", summary: "s", url: null,
    status: "built", text: "# Ship an app", sections: [],
  }));
  const [hit] = await nc.Docs.search("deploy an app", { limit: 5 });
  assert.equal(hit.id, "guide:apps");
  assert.equal(searched.last.query.get("q"), "deploy an app");
  assert.equal(searched.last.query.get("limit"), "5");
  assert.equal(searched.last.headers.get("Authorization"), null);
  assert.equal((await nc.Docs.read("skill:ship-an-app")).text, "# Ship an app");
  assert.equal(read.last.headers.get("Authorization"), null);
});

test("Key.redeemSetupCode redeems a code for the key, once, with no key", async () => {
  const { api } = setup();
  const redeemed = api.on("POST", "/v1/setup", json({
    object: "setup_key", key: "nk_live_FAKESECRET0002", key_id: "key_9", key_name: "Coding agent",
    key_prefix: "nk_live_FAKE", email: "ana@acme.test",
  }));
  const key = await nc.Key.redeemSetupCode("nc_setup_abc");
  assert.equal(redeemed.last.body, "code=nc_setup_abc");
  assert.equal(redeemed.last.headers.get("Authorization"), null);
  assert.deepEqual([key.id, key.name, key.secret, key.raw.email], ["key_9", "Coding agent", "nk_live_FAKESECRET0002", "ana@acme.test"]);
  assert.equal("key" in key.raw, false);
});

test("app.live.change hands the change to the app's coding agent", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects", json({ object: "list", data: [{ object: "project", id: "prj_1", name: "larkspur" }] }));
  const handed = api.on("POST", "/v1/projects/prj_1/live/changes", json(operation({ id: "op_c", kind: "agent.message", status: "running" }), { status: 202 }));
  const app = nc.Project.fromName("larkspur");
  const op = await app.live.change("Add a dark mode toggle", { title: "Dark mode" });
  assert.deepEqual(handed.last.body, { text: "Add a dark mode toggle", title: "Dark mode" });
  assert.equal(op.id, "op_c");
});
