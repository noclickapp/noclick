/**
 * What the CLI shows before a command runs: `noclick` alone, `noclick --help` (`--all` for every API area), a
 * command it doesn't have, and a command's examples. The words are the manifest's `screens`, written from the
 * Python CLI's `noclick/_cli/screens.py`, so both CLIs draw the same screens.
 */

import type { Screens } from "./spec.ts";

type Row = readonly [string, string];

const rows = (list: Iterable<Row>, width: number) => [...list].map(([name, text]) => `  ${name.padEnd(width)}  ${text}`);

export function signedIn(email: string | null | undefined, fromEnv?: string): string | null {
  if (fromEnv) return `Signed in with ${fromEnv}`;
  return email ? `Signed in as ${email}` : null;
}

/** `noclick` alone: what it is, the three things to do first, where to go next. */
export function first(screens: Screens, said: string | null, linkedApp: string | null): string {
  const lines = [screens.intro, ""];
  let start: Row[] = screens.first;
  if (said) {
    lines.push(said + (linkedApp ? `; this folder is linked to ${linkedApp}.` : "."));
    start = start.slice(1);
  }
  const width = Math.max(...[...start, ...screens.next].map(([name]) => name.length));
  const shown = rows(start, width);
  if (!said) shown.splice(1, 0, `  ${screens.signed_out}`); // beside signing in: an agent with no person to sign in
  lines.push("Start here:", ...shown, "", "Then:", ...rows(screens.next, width));
  return lines.join("\n");
}

/** The harness running the CLI, by what it sets in the environment, else `cli`. */
export function harness(screens: Screens, env: Record<string, string | undefined>): string {
  return screens.signup.harnesses.find(([name]) => env[name])?.[1] ?? "cli";
}

export function unclaimed(claimUrl: string | null | undefined): string {
  return `unclaimed: give your person ${claimUrl ?? "a claim link (noclick api POST /v1/agent_signups/current/claim_link makes one)"}`;
}

/** The commands by section, one line each, then the API's areas: one line, or (`areas`) each of them. */
export function commands(screens: Screens, areas: Map<string, number> | null): string {
  const names = screens.sections.flatMap((s) => s.commands.map(([n]) => n));
  const width = Math.max(...[...names, screens.areas[0], ...(areas?.keys() ?? [])].map((n) => n.length));
  const lines: string[] = [];
  for (const section of screens.sections) {
    lines.push(`${section.name}:`, ...rows(section.commands, width));
    if (section.name === "Everything else") {
      if (!areas) lines.push(...rows([screens.areas], width));
      else {
        const sorted = [...areas].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
        lines.push(...rows(sorted.map(([area, n]) => [area, `${n} API operation${n === 1 ? "" : "s"}: noclick ${area} --help lists them.`] as const), width));
      }
    }
    lines.push("");
  }
  return lines.join("\n").trimEnd();
}

/** A command line naming a command there isn't: the closest curated commands, else the closest API areas (under
 * a group, its commands and operations alike). */
export function unknown(word: string, within: string[], curated: string[], areas: string[]): string {
  const said = [...within, word].join(" ");
  const pools = within.length ? [[...curated, ...areas]] : [curated, areas];
  const near = pools.map((pool) => closeMatches(word, pool)).find((found) => found.length) ?? [];
  const mean = near.length ? ` Did you mean: ${near.map((n) => [...within, n].join(" ")).join(", ")}?` : "";
  return [`Unknown command '${said}'.${mean}`, `Every command: ${["noclick", ...within].join(" ")} --help`].join("\n");
}

// --- Python's difflib.get_close_matches, so both CLIs suggest the same names ------------------------------------

function matched(a: string, b: string): number {
  const b2j = new Map<string, number[]>();
  for (let j = 0; j < b.length; j++) b2j.set(b[j]!, [...(b2j.get(b[j]!) ?? []), j]);
  let total = 0;
  const queue: [number, number, number, number][] = [[0, a.length, 0, b.length]];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop()!;
    let [besti, bestj, size] = [alo, blo, 0];
    let lens = new Map<number, number>();
    for (let i = alo; i < ahi; i++) {
      const next = new Map<number, number>();
      for (const j of b2j.get(a[i]!) ?? []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (lens.get(j - 1) ?? 0) + 1;
        next.set(j, k);
        if (k > size) [besti, bestj, size] = [i - k + 1, j - k + 1, k];
      }
      lens = next;
    }
    if (!size) continue;
    total += size;
    if (alo < besti && blo < bestj) queue.push([alo, besti, blo, bestj]);
    if (besti + size < ahi && bestj + size < bhi) queue.push([besti + size, ahi, bestj + size, bhi]);
  }
  return total;
}

/** The (at most `n`) names of `pool` whose likeness to `word` is `cutoff` or more, likest first. */
export function closeMatches(word: string, pool: string[], n = 3, cutoff = 0.6): string[] {
  const scored = pool
    .map((name) => [(2 * matched(name, word)) / (name.length + word.length), name] as const)
    .filter(([score]) => score >= cutoff);
  scored.sort(([s1, x1], [s2, x2]) => s2 - s1 || (x2 < x1 ? -1 : x2 > x1 ? 1 : 0));
  return scored.slice(0, n).map(([, name]) => name);
}
