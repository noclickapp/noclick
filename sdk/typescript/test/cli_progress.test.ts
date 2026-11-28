// A release's progress as both CLIs draw it: the Python CLI's cases (python/tests/cli_progress_cases.json, written
// from its renderer) hold this one to the same lines at a terminal and anywhere else.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Detached, Follower, Steps, follow, took } from "../src/cli/progress.ts";
import { Style } from "../src/cli/style.ts";

interface Event { at: number; start?: string; end?: boolean; tick?: number; apply?: Record<string, unknown>; single?: string }
interface Case { name: string; events?: Event[]; plain?: string; live?: string; took?: [number, string][] }

const cases = (JSON.parse(readFileSync(new URL("../../python/tests/cli_progress_cases.json", import.meta.url), "utf8")) as { cases: Case[] }).cases;

function render(events: Event[], live: boolean): string {
  const out: string[] = [];
  let now = 0;
  const steps = new Steps((text) => out.push(text), { live, clock: () => now, paint: new Style(false), ticker: false });
  const follower = new Follower(steps, events.find((e) => e.single)?.single);
  for (const event of events) {
    now = event.at;
    if (event.start !== undefined) steps.start(event.start);
    if (event.end !== undefined) steps.end(event.end);
    if (event.tick !== undefined) steps.tick();
    if (event.apply !== undefined) follower.apply(event.apply);
  }
  steps.close();
  return out.join("");
}

for (const c of cases.filter((c) => c.events)) {
  test(`both ways of drawing a release print what the cases say: ${c.name}`, () => {
    assert.equal(render(c.events!, false), c.plain);
    assert.equal(render(c.events!, true), c.live);
  });
}

test("times cut to tenths, then minutes", () => {
  for (const [seconds, said] of cases.find((c) => c.name === "took")!.took!) assert.equal(took(seconds), said);
});

test("following reads each change once, names what it saw, and stops where Ctrl-C does", async () => {
  const reads: [string, number, string | null][] = [];
  let interrupt = () => {};
  const interrupted = new Promise<void>((resolve) => { interrupt = resolve; });
  const out: string[] = [];
  const steps = new Steps((text) => out.push(text), { live: false, ticker: false });
  const read = async (opId: string, windowS: number, changedSince: string | null) => {
    reads.push([opId, windowS, changedSince]);
    if (reads.length === 1) {
      return { status: "running", updated_at: "t2", progress: { stages: [{ name: "Building", status: "current" }], lines: ["> vite build"], line_count: 1 } };
    }
    interrupt();
    return await new Promise<Record<string, unknown>>(() => {});
  };
  await assert.rejects(follow("op_d", { status: "queued", updated_at: "t1", progress: null }, steps, read,
    { timeoutS: 30, interrupted, clock: () => 0 }), Detached);
  assert.deepEqual(reads, [["op_d", 30, "t1"], ["op_d", 30, "t2"]]);
  assert.equal(out.join(""), "Build…\n  > vite build\n");
});
