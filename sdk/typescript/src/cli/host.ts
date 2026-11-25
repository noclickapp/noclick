/** What the curated commands take from the process they run in: tests hand in their own. */

import { readFileSync } from "node:fs";

export interface Host {
  env: Record<string, string | undefined>;
  cwd(): string;
  /** All of stdin, as text. */
  stdin(): Promise<string>;
  stdinIsTty(): boolean;
  sleep(ms: number): Promise<void>;
  /** The fetch every client a command makes uses (the global one unless a test sets it). */
  fetch?: typeof fetch;
  /** Put the profile's key on the default client: what a command that signs in itself (`whoami`) calls. */
  signIn(profile: string): void;
}

export const host: Host = {
  env: process.env,
  cwd: () => process.cwd(),
  stdin: async () => readFileSync(0, "utf8"),
  stdinIsTty: () => Boolean(process.stdin.isTTY),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  signIn: () => {
    throw new Error("host.signIn is set by main");
  },
};
