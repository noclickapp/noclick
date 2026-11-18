// The version the client reports is the one it's published as: `VERSION` (sent in the User-Agent) is written by
// hand, so a release that raises package.json and package-lock.json must raise it too.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { VERSION } from "../src/index.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../${name}`, import.meta.url), "utf8"));

test("VERSION is package.json's version, and package-lock.json's", () => {
  const lock = read("package-lock.json");
  assert.equal(VERSION, read("package.json").version);
  assert.equal(lock.version, VERSION);
  assert.equal(lock.packages[""].version, VERSION);
});
