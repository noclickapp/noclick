// src/index.ts is one name per line, in order (scripts/export_list.ts), so two changes adding names merge cleanly.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { INDEX, canonical } from "../scripts/export_list.ts";

test("the export list is one name per line, in order", () => {
  assert.equal(readFileSync(INDEX, "utf8"), canonical(readFileSync(INDEX, "utf8")),
    "run: node --experimental-strip-types scripts/export_list.ts");
});
